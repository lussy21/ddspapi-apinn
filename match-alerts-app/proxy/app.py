import os
import json
import base64
import hmac
import requests
from pywebpush import webpush, WebPushException
from flask import Flask, request, jsonify, make_response, send_from_directory

app = Flask(__name__)

APPS_SCRIPT_URL = os.environ.get(
    "APPS_SCRIPT_URL",
    "https://script.google.com/macros/s/AKfycbwRUaBGKeUQm-L2P2mar42FXVdHAB1mNGkxCscnMMDAk_BDZXq2ADZyXo7YZI7NH89Z/exec",
)
APP_ORIGIN = os.environ.get("APP_ORIGIN", "https://match-alerts-private.onrender.com")
SITE_ORIGIN = os.environ.get("SITE_ORIGIN", "https://dreamteamtips-site.onrender.com")
ALLOWED_ORIGINS = {APP_ORIGIN, SITE_ORIGIN}
APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ADMIN_DIR = os.path.join(APP_DIR, "admin")
AUTO_PUSH_SECRET = os.environ.get("AUTO_PUSH_SECRET", "").strip()
VAPID_PRIVATE_KEY_B64 = os.environ.get("VAPID_PRIVATE_KEY_B64", "").strip()
VAPID_PRIVATE_KEY = os.environ.get("VAPID_PRIVATE_KEY", "").strip()
VAPID_SUBJECT = os.environ.get("VAPID_SUBJECT", "mailto:support@dreamteamtips.com").strip()
AUTO_ALERTS_TO_CUSTOMERS = os.environ.get("AUTO_ALERTS_TO_CUSTOMERS", "0").strip() == "1"


def _normalize_vapid_key(value):
    raw = str(value or "").strip()
    if not raw:
        return ""

    # py_vapid.from_string expects a base64/base64url encoded RAW or DER key.
    # If Render stores a PEM string, remove the PEM wrapper and pass only the
    # encoded key body. This avoids ValueError during VAPID parsing.
    if "-----BEGIN" in raw:
        lines = [
            line.strip()
            for line in raw.splitlines()
            if line.strip() and not line.startswith("-----")
        ]
        return "".join(lines)

    return raw.replace("\n", "").replace("\r", "").strip()


def get_vapid_private_key():
    if VAPID_PRIVATE_KEY:
        return _normalize_vapid_key(VAPID_PRIVATE_KEY)

    if VAPID_PRIVATE_KEY_B64:
        # This variable is intentionally allowed to contain either:
        # 1) base64(PKCS8 PEM), or 2) a directly encoded RAW/DER VAPID key.
        # Support both so existing Render secrets remain valid.
        try:
            decoded = base64.b64decode(VAPID_PRIVATE_KEY_B64)
        except Exception:
            return _normalize_vapid_key(VAPID_PRIVATE_KEY_B64)

        try:
            text_value = decoded.decode("utf-8").strip()
        except UnicodeDecodeError:
            return base64.urlsafe_b64encode(decoded).decode("ascii").rstrip("=")

        if "-----BEGIN" in text_value:
            return _normalize_vapid_key(text_value)

        # If the decoded value is itself a plausible encoded key, use it.
        compact = _normalize_vapid_key(text_value)
        if compact:
            return compact

        return base64.urlsafe_b64encode(decoded).decode("ascii").rstrip("=")

    return ""


def upstream_post_direct(data, timeout=(4, 15)):
    upstream = requests.post(
        APPS_SCRIPT_URL,
        data={k: "" if v is None else str(v) for k, v in data.items()},
        timeout=timeout,
        allow_redirects=True,
    )
    try:
        return upstream.json()
    except ValueError:
        raise RuntimeError("BACKEND_BAD_RESPONSE")



def push_to_all_active_users(admin_code, title, body, tag):
    vapid_private_key = get_vapid_private_key()
    if not vapid_private_key:
        return {"sent": 0, "failed": 0, "removed": 0, "total": 0, "error": "PUSH_NOT_CONFIGURED"}

    try:
        target_data = upstream_post_direct(
            {"action": "adminPushTargets", "adminCode": str(admin_code or "")},
            timeout=(4, 15),
        )
    except requests.RequestException:
        return {"sent": 0, "failed": 0, "removed": 0, "total": 0, "error": "BACKEND_UNREACHABLE"}
    except RuntimeError:
        return {"sent": 0, "failed": 0, "removed": 0, "total": 0, "error": "BACKEND_BAD_RESPONSE"}

    if not target_data.get("ok"):
        return {"sent": 0, "failed": 0, "removed": 0, "total": 0, "error": str(target_data.get("error") or "PUSH_TARGETS_FAILED")}

    targets = target_data.get("targets", [])
    sent = 0
    failed = 0
    removed = 0
    failure_codes = {}
    message = json.dumps(
        {"title": title, "body": body, "url": "./", "tag": tag},
        ensure_ascii=False,
    )

    for target in targets:
        subscription = {
            "endpoint": target.get("endpoint", ""),
            "keys": target.get("keys") or {},
        }
        if not subscription["endpoint"]:
            continue
        try:
            webpush(
                subscription_info=subscription,
                data=message,
                vapid_private_key=vapid_private_key,
                vapid_claims={"sub": VAPID_SUBJECT},
                ttl=900,
            )
            sent += 1
        except WebPushException as exc:
            failed += 1
            status = getattr(getattr(exc, "response", None), "status_code", None)
            code = "webpush_" + str(status or "unknown")
            failure_codes[code] = failure_codes.get(code, 0) + 1
            if status in (404, 410) and target.get("key"):
                try:
                    cleanup = upstream_post_direct(
                        {
                            "action": "adminPushDelete",
                            "adminCode": str(admin_code or ""),
                            "key": target.get("key", ""),
                        },
                        timeout=(4, 15),
                    )
                    if cleanup.get("ok"):
                        removed += 1
                except Exception:
                    pass
        except Exception as exc:
            failed += 1
            code = "client_" + exc.__class__.__name__
            failure_codes[code] = failure_codes.get(code, 0) + 1

    return {
        "sent": sent,
        "failed": failed,
        "removed": removed,
        "total": int(target_data.get("count") or 0),
        "failureCodes": failure_codes,
    }



def push_owner_new_alerts(alerts):
    """Send model-open notifications only to the owner/admin push targets."""
    new_alerts = [
        item for item in (alerts or [])
        if isinstance(item, dict) and str(item.get("event") or "").strip() == "ΑΝΟΙΞΕ"
    ]
    if not new_alerts:
        return {"sent": 0, "failed": 0, "removed": 0, "total": 0, "alerts": 0}

    vapid_private_key = get_vapid_private_key()
    if not vapid_private_key:
        return {"sent": 0, "failed": 0, "removed": 0, "total": 0, "alerts": len(new_alerts), "error": "PUSH_NOT_CONFIGURED"}

    try:
        target_data = upstream_post_direct(
            {"action": "automationOwnerPushTargets", "secret": AUTO_PUSH_SECRET},
            timeout=(4, 15),
        )
    except requests.RequestException:
        return {"sent": 0, "failed": 0, "removed": 0, "total": 0, "alerts": len(new_alerts), "error": "BACKEND_UNREACHABLE"}
    except RuntimeError:
        return {"sent": 0, "failed": 0, "removed": 0, "total": 0, "alerts": len(new_alerts), "error": "BACKEND_BAD_RESPONSE"}

    if not target_data.get("ok"):
        return {
            "sent": 0,
            "failed": 0,
            "removed": 0,
            "total": 0,
            "alerts": len(new_alerts),
            "error": str(target_data.get("error") or "OWNER_PUSH_TARGETS_FAILED"),
        }

    targets = target_data.get("targets", [])
    sent = 0
    failed = 0
    removed = 0
    failure_codes = {}

    for item in new_alerts:
        match_name = str(item.get("match") or "").strip().replace(" - ", " – ")
        alert_name = str(item.get("alert") or "").strip()
        body = match_name or "Νέο alert DreamTeamTips"
        if alert_name:
            body += " · " + alert_name
        target_url = (
            APP_ORIGIN
            + "/admin/?daily=1&match="
            + requests.utils.quote(str(item.get("match") or "").strip())
        )
        tag = "dreamteamtips-owner-new-" + str(item.get("key") or "alert")
        message = json.dumps(
            {
                "title": "🔔 Νέο καμπανάκι",
                "body": body[:220],
                "url": target_url,
                "tag": tag,
            },
            ensure_ascii=False,
        )

        for target in targets:
            subscription = {
                "endpoint": target.get("endpoint", ""),
                "keys": target.get("keys") or {},
            }
            if not subscription["endpoint"]:
                continue
            try:
                webpush(
                    subscription_info=subscription,
                    data=message,
                    vapid_private_key=vapid_private_key,
                    vapid_claims={"sub": VAPID_SUBJECT},
                    ttl=900,
                )
                sent += 1
            except WebPushException as exc:
                failed += 1
                status = getattr(getattr(exc, "response", None), "status_code", None)
                code = "webpush_" + str(status or "unknown")
                failure_codes[code] = failure_codes.get(code, 0) + 1
                if status in (404, 410) and target.get("key"):
                    try:
                        cleanup = upstream_post_direct(
                            {
                                "action": "automationOwnerPushDelete",
                                "secret": AUTO_PUSH_SECRET,
                                "key": target.get("key", ""),
                            },
                            timeout=(4, 15),
                        )
                        if cleanup.get("ok"):
                            removed += 1
                    except Exception:
                        pass
            except Exception as exc:
                failed += 1
                code = "client_" + exc.__class__.__name__
                failure_codes[code] = failure_codes.get(code, 0) + 1

    return {
        "sent": sent,
        "failed": failed,
        "removed": removed,
        "total": int(target_data.get("count") or 0),
        "alerts": len(new_alerts),
        "failureCodes": failure_codes,
    }


def cors(resp):
    origin = request.headers.get("Origin", "")
    resp.headers["Access-Control-Allow-Origin"] = origin if origin in ALLOWED_ORIGINS else APP_ORIGIN
    resp.headers["Vary"] = "Origin"
    resp.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS, GET"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.after_request
def add_headers(resp):
    return cors(resp)


@app.get("/health")
def health():
    return jsonify(ok=True, service="match-alerts-api")


@app.get("/admin")
@app.get("/admin/")
def admin_page():
    return send_from_directory(ADMIN_DIR, "index.html")


@app.get("/admin/<path:filename>")
def admin_asset(filename):
    return send_from_directory(ADMIN_DIR, filename)


@app.post("/internal/alerts-push")
def internal_alerts_push():
    supplied = request.headers.get("X-Auto-Push-Secret", "")
    if not AUTO_PUSH_SECRET or not hmac.compare_digest(supplied, AUTO_PUSH_SECRET):
        return jsonify(ok=False, error="AUTOMATION_UNAUTHORIZED"), 403

    payload = request.get_json(silent=True) or {}
    alerts = payload.get("alerts") or []
    if not isinstance(alerts, list) or not alerts:
        return jsonify(ok=True, sent=0, failed=0, removed=0, total=0), 200

    # Owner notifications are independent from customer auto-push.
    # Only brand-new model alerts (ΑΝΟΙΞΕ) are sent to owner/admin devices.
    owner_push = push_owner_new_alerts(alerts)

    if not AUTO_ALERTS_TO_CUSTOMERS:
        return jsonify(
            ok=True,
            sent=int(owner_push.get("sent") or 0),
            failed=int(owner_push.get("failed") or 0),
            removed=int(owner_push.get("removed") or 0),
            total=int(owner_push.get("total") or 0),
            ownerAlerts=int(owner_push.get("alerts") or 0),
            ownerOnly=True,
            customersSuppressed=True,
            reason="ADMIN_APPROVAL_REQUIRED",
            failureCodes=owner_push.get("failureCodes", {}),
            ownerError=owner_push.get("error", ""),
        ), 200

    count = len(alerts)

    def clean_match(value):
        text_value = str(value or "").strip()
        return text_value.replace(" - ", " – ")

    def alert_action(item):
        event = str(item.get("event") or "").strip()
        if event == "ΕΦΥΓΕ":
            return "removed"
        if event == "ΑΛΛΑΞΕ ALERT":
            return "changed"
        return "new"

    if count == 1:
        item = alerts[0] if isinstance(alerts[0], dict) else {}
        action = alert_action(item)
        match_name = clean_match(item.get("match"))
        if action == "removed":
            title = "Επιλογή αποσύρθηκε"
        elif action == "changed":
            title = "Επιλογή ενημερώθηκε"
        else:
            title = "Νέα επιλογή"
        body = match_name or "DreamTeamTips"
        target_url = "./?match=" + requests.utils.quote(str(item.get("match") or "").strip())
        tag = "dreamteamtips-" + action + "-" + str(item.get("key") or "update")
    else:
        groups = {"new": [], "changed": [], "removed": []}
        for raw_item in alerts:
            item = raw_item if isinstance(raw_item, dict) else {}
            name = clean_match(item.get("match"))
            if name:
                groups[alert_action(item)].append(name)

        parts = []
        labels = (("new", "Νέα"), ("changed", "Άλλαξαν"), ("removed", "Αποσύρθηκαν"))
        for key_name, label in labels:
            names = groups[key_name]
            if not names:
                continue
            shown = names[:3]
            piece = label + ": " + ", ".join(shown)
            if len(names) > len(shown):
                piece += f" +{len(names) - len(shown)}"
            parts.append(piece)

        title = f"{count} ενημερώσεις επιλογών"
        body = " · ".join(parts) if parts else f"{count} ενημερώσεις στις επιλογές"
        if len(body) > 220:
            body = body[:217].rstrip() + "…"
        target_url = "./"
        tag = "dreamteamtips-picks-update"

    vapid_private_key = get_vapid_private_key()
    if not vapid_private_key:
        return jsonify(ok=False, error="PUSH_NOT_CONFIGURED"), 500

    try:
        target_data = upstream_post_direct(
            {"action": "automationPushTargets", "secret": AUTO_PUSH_SECRET},
            timeout=(4, 15),
        )
    except requests.RequestException:
        return jsonify(ok=False, error="BACKEND_UNREACHABLE"), 502
    except RuntimeError:
        return jsonify(ok=False, error="BACKEND_BAD_RESPONSE"), 502

    if not target_data.get("ok"):
        return jsonify(target_data), 200

    sent = 0
    failed = 0
    removed = 0
    message = json.dumps(
        {
            "title": title,
            "body": body,
            "url": target_url,
            "tag": tag,
        },
        ensure_ascii=False,
    )

    for target in target_data.get("targets", []):
        subscription = {
            "endpoint": target.get("endpoint", ""),
            "keys": target.get("keys") or {},
        }
        if not subscription["endpoint"]:
            continue
        try:
            webpush(
                subscription_info=subscription,
                data=message,
                vapid_private_key=vapid_private_key,
                vapid_claims={"sub": VAPID_SUBJECT},
                ttl=900,
            )
            sent += 1
        except WebPushException as exc:
            failed += 1
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status in (404, 410) and target.get("key"):
                try:
                    cleanup = upstream_post_direct(
                        {
                            "action": "automationPushDelete",
                            "secret": AUTO_PUSH_SECRET,
                            "key": target.get("key", ""),
                        }
                    )
                    if cleanup.get("ok"):
                        removed += 1
                except Exception:
                    pass
        except Exception:
            failed += 1

    return jsonify(
        ok=True,
        sent=sent,
        failed=failed,
        removed=removed,
        total=int(target_data.get("count") or 0),
        alerts=count,
    ), 200


@app.route("/api", methods=["POST", "OPTIONS"])
def api():
    if request.method == "OPTIONS":
        return make_response("", 204)

    origin = request.headers.get("Origin", "")
    same_origin = request.host_url.rstrip("/")
    if origin and origin not in (ALLOWED_ORIGINS | {same_origin}):
        return jsonify(ok=False, error="ORIGIN_DENIED"), 403

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        payload = request.form.to_dict(flat=True)

    payload.pop("bridge", None)
    payload.pop("requestId", None)

    def upstream_post(data, timeout=(4, 10)):
        upstream = requests.post(
            APPS_SCRIPT_URL,
            data={k: "" if v is None else str(v) for k, v in data.items()},
            timeout=timeout,
            allow_redirects=True,
        )
        try:
            return upstream.json()
        except ValueError:
            raise RuntimeError("BACKEND_BAD_RESPONSE")

    if payload.get("action") == "adminAutomationSetup":
        if not AUTO_PUSH_SECRET:
            return jsonify(ok=False, error="AUTOMATION_NOT_CONFIGURED"), 500
        try:
            data = upstream_post(
                {
                    "action": "adminAutomationSetup",
                    "adminCode": str(payload.get("adminCode") or ""),
                    "secret": AUTO_PUSH_SECRET,
                },
                timeout=(4, 15),
            )
        except requests.RequestException:
            return jsonify(ok=False, error="BACKEND_UNREACHABLE"), 502
        except RuntimeError:
            return jsonify(ok=False, error="BACKEND_BAD_RESPONSE"), 502
        return jsonify(data), 200

    if payload.get("action") in {"adminSignalPublish", "adminSignalEdit"}:
        action = str(payload.get("action") or "")
        admin_code = str(payload.get("adminCode") or "")
        control_id = str(payload.get("controlId") or "").strip()
        pick = str(payload.get("pick") or "").strip()

        request_data = {
            "action": action,
            "adminCode": admin_code,
            "controlId": control_id,
        }
        if action == "adminSignalEdit":
            request_data["pick"] = pick

        try:
            data = upstream_post(request_data, timeout=(4, 35))
        except requests.RequestException:
            return jsonify(ok=False, error="BACKEND_UNREACHABLE"), 502
        except RuntimeError:
            return jsonify(ok=False, error="BACKEND_BAD_RESPONSE"), 502

        if not data.get("ok"):
            return jsonify(data), 200

        home = str(data.get("home") or "").strip()
        away = str(data.get("away") or "").strip()
        public_pick = str(data.get("pick") or "").strip()
        odds = data.get("odds")
        odds_text = ""
        try:
            if float(odds) > 1:
                odds_text = " @ " + ("%.2f" % float(odds)).replace(".", ",")
        except (TypeError, ValueError):
            pass

        title = "Νέα επιλογή" if action == "adminSignalPublish" else "Επιλογή ενημερώθηκε"
        match_name = (home + " – " + away).strip(" –")
        body = match_name + ((" · " + public_pick + odds_text) if public_pick else "")
        if not body:
            body = "Νέα ενημέρωση DreamTeamTips."

        push = push_to_all_active_users(
            admin_code,
            title,
            body,
            "dreamteamtips-" + ("publish-" if action == "adminSignalPublish" else "edit-") + control_id,
        )
        data["pushSent"] = push.get("sent", 0)
        data["pushFailed"] = push.get("failed", 0)
        data["pushRemoved"] = push.get("removed", 0)
        data["pushTotal"] = push.get("total", 0)
        data["pushFailureCodes"] = push.get("failureCodes", {})
        return jsonify(data), 200

    if payload.get("action") == "adminSlipPublish":
        admin_code = str(payload.get("adminCode") or "")
        try:
            data = upstream_post(payload, timeout=(4, 35))
        except requests.RequestException:
            return jsonify(ok=False, error="BACKEND_UNREACHABLE"), 502
        except RuntimeError:
            return jsonify(ok=False, error="BACKEND_BAD_RESPONSE"), 502
        if not data.get("ok"):
            return jsonify(data), 200

        slip = data.get("slip") or {}
        label = str(slip.get("label") or "Νέο δελτίο").strip()
        total_odds = slip.get("totalOdds")
        odds_text = ""
        try:
            if float(total_odds) > 1:
                odds_text = " · συνολική απόδοση " + ("%.2f" % float(total_odds)).replace(".", ",")
        except (TypeError, ValueError):
            pass

        push = push_to_all_active_users(
            admin_code,
            "Νέο δελτίο DreamTeamTips",
            label + odds_text,
            "dreamteamtips-slip-" + str(slip.get("id") or "new"),
        )
        data["pushSent"] = push.get("sent", 0)
        data["pushFailed"] = push.get("failed", 0)
        data["pushRemoved"] = push.get("removed", 0)
        data["pushTotal"] = push.get("total", 0)
        return jsonify(data), 200

    if payload.get("action") == "adminSlipWithdraw":
        admin_code = str(payload.get("adminCode") or "")
        try:
            data = upstream_post(payload, timeout=(4, 15))
        except requests.RequestException:
            return jsonify(ok=False, error="BACKEND_UNREACHABLE"), 502
        except RuntimeError:
            return jsonify(ok=False, error="BACKEND_BAD_RESPONSE"), 502
        if not data.get("ok"):
            return jsonify(data), 200

        push = push_to_all_active_users(
            admin_code,
            "Δελτίο αποσύρθηκε",
            "Ένα δελτίο του DreamTeamTips αποσύρθηκε.",
            "dreamteamtips-slip-withdraw-" + str(payload.get("slipId") or ""),
        )
        data["pushSent"] = push.get("sent", 0)
        data["pushFailed"] = push.get("failed", 0)
        data["pushRemoved"] = push.get("removed", 0)
        data["pushTotal"] = push.get("total", 0)
        return jsonify(data), 200

    if payload.get("action") == "adminSignalWithdraw":
        admin_code = str(payload.get("adminCode") or "")
        control_id = str(payload.get("controlId") or "").strip()

        try:
            data = upstream_post(
                {
                    "action": "adminSignalWithdraw",
                    "adminCode": admin_code,
                    "controlId": control_id,
                },
                timeout=(4, 35),
            )
        except requests.RequestException:
            return jsonify(ok=False, error="BACKEND_UNREACHABLE"), 502
        except RuntimeError:
            return jsonify(ok=False, error="BACKEND_BAD_RESPONSE"), 502

        if not data.get("ok"):
            return jsonify(data), 200

        if data.get("wasPublished"):
            home = str(data.get("home") or "").strip()
            away = str(data.get("away") or "").strip()
            pick = str(data.get("pick") or "").strip()
            match_name = (home + " – " + away).strip(" –")
            body = match_name + ((" · " + pick) if pick else "")
            if not body:
                body = "Μία επιλογή του DreamTeamTips αποσύρθηκε."
            push = push_to_all_active_users(
                admin_code,
                "Επιλογή αποσύρθηκε",
                body,
                "dreamteamtips-withdraw-" + control_id,
            )
            data["pushSent"] = push.get("sent", 0)
            data["pushFailed"] = push.get("failed", 0)
            data["pushRemoved"] = push.get("removed", 0)
            data["pushTotal"] = push.get("total", 0)
            data["pushFailureCodes"] = push.get("failureCodes", {})
        else:
            data["pushSent"] = 0
            data["pushFailed"] = 0
            data["pushRemoved"] = 0
            data["pushTotal"] = 0

        data.pop("savedBy", None)
        return jsonify(data), 200

    if payload.get("action") == "adminPushSend":
        title = str(payload.get("title") or "").strip()[:80]
        body = str(payload.get("body") or "").strip()[:220]
        admin_code = str(payload.get("adminCode") or "")
        if not title or not body:
            return jsonify(ok=False, error="BAD_PUSH_MESSAGE"), 200
        if not get_vapid_private_key():
            return jsonify(ok=False, error="PUSH_NOT_CONFIGURED"), 500

        try:
            message_data = upstream_post(
                {
                    "action": "adminMessageCreate",
                    "adminCode": admin_code,
                    "title": title,
                    "body": body,
                },
                timeout=(4, 15),
            )
            if not message_data.get("ok"):
                return jsonify(message_data), 200

            target_data = upstream_post(
                {"action": "adminPushTargets", "adminCode": admin_code},
                timeout=(4, 15),
            )
        except requests.RequestException:
            return jsonify(ok=False, error="BACKEND_UNREACHABLE"), 502
        except RuntimeError:
            return jsonify(ok=False, error="BACKEND_BAD_RESPONSE"), 502

        if not target_data.get("ok"):
            return jsonify(target_data), 200

        vapid_private_key = get_vapid_private_key()
        if not vapid_private_key:
            return jsonify(ok=False, error="PUSH_NOT_CONFIGURED"), 500

        sent = 0
        failed = 0
        removed = 0
        failure_codes = {}
        message = json.dumps(
            {"title": title, "body": body, "url": "./", "tag": "dreamteamtips-admin"},
            ensure_ascii=False,
        )

        for target in target_data.get("targets", []):
            subscription = {
                "endpoint": target.get("endpoint", ""),
                "keys": target.get("keys") or {},
            }
            if not subscription["endpoint"]:
                continue
            try:
                webpush(
                    subscription_info=subscription,
                    data=message,
                    vapid_private_key=vapid_private_key,
                    vapid_claims={"sub": VAPID_SUBJECT},
                    ttl=900,
                )
                sent += 1
            except WebPushException as exc:
                failed += 1
                status = getattr(getattr(exc, "response", None), "status_code", None)
                code = "webpush_" + str(status or "unknown")
                failure_codes[code] = failure_codes.get(code, 0) + 1
                app.logger.warning("manual_push_failure code=%s", code)
                if status in (404, 410) and target.get("key"):
                    try:
                        cleanup = upstream_post(
                            {
                                "action": "adminPushDelete",
                                "adminCode": admin_code,
                                "key": target.get("key", ""),
                            }
                        )
                        if cleanup.get("ok"):
                            removed += 1
                    except Exception:
                        pass
            except Exception as exc:
                failed += 1
                code = "client_" + exc.__class__.__name__
                failure_codes[code] = failure_codes.get(code, 0) + 1
                app.logger.warning("manual_push_failure code=%s", code)

        total = int(target_data.get("count") or 0)
        app.logger.info(
            "manual_push_result total=%s sent=%s failed=%s removed=%s",
            total,
            sent,
            failed,
            removed,
        )
        return jsonify(
            ok=True,
            messageSaved=True,
            messageId=(message_data.get("message") or {}).get("id", ""),
            sent=sent,
            failed=failed,
            removed=removed,
            total=total,
            failureCodes=failure_codes,
        ), 200

    try:
        slow_actions = {"alerts", "adminSignals", "officialHistory", "adminPlayedHistory", "adminSignalKeep"}
        timeout = (4, 35) if payload.get("action") in slow_actions else (4, 10)
        data = upstream_post(payload, timeout=timeout)
    except requests.RequestException:
        return jsonify(ok=False, error="BACKEND_UNREACHABLE"), 502
    except RuntimeError:
        return jsonify(ok=False, error="BACKEND_BAD_RESPONSE"), 502

    return jsonify(data), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
