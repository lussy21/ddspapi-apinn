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
APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ADMIN_DIR = os.path.join(APP_DIR, "admin")
AUTO_PUSH_SECRET = os.environ.get("AUTO_PUSH_SECRET", "").strip()
VAPID_PRIVATE_KEY_B64 = os.environ.get("VAPID_PRIVATE_KEY_B64", "").strip()
VAPID_PRIVATE_KEY = os.environ.get("VAPID_PRIVATE_KEY", "").strip()
VAPID_SUBJECT = os.environ.get("VAPID_SUBJECT", "mailto:support@dreamteamtips.com").strip()


def get_vapid_private_key():
    if VAPID_PRIVATE_KEY:
        return VAPID_PRIVATE_KEY
    if VAPID_PRIVATE_KEY_B64:
        try:
            return base64.b64decode(VAPID_PRIVATE_KEY_B64).decode("utf-8")
        except Exception:
            return ""
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



def cors(resp):
    resp.headers["Access-Control-Allow-Origin"] = APP_ORIGIN
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

    count = len(alerts)
    title = "DreamTeamTips"
    body = "Νέα επιλογή διαθέσιμη" if count == 1 else f"{count} νέες επιλογές διαθέσιμες"

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
            "url": "./",
            "tag": "dreamteamtips-new-picks",
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
    if origin and origin not in {APP_ORIGIN, same_origin}:
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
            except Exception:
                failed += 1

        return jsonify(
            ok=True,
            messageSaved=True,
            messageId=(message_data.get("message") or {}).get("id", ""),
            sent=sent,
            failed=failed,
            removed=removed,
            total=int(target_data.get("count") or 0),
        ), 200

    try:
        timeout = (4, 35) if payload.get("action") == "alerts" else (4, 10)
        data = upstream_post(payload, timeout=timeout)
    except requests.RequestException:
        return jsonify(ok=False, error="BACKEND_UNREACHABLE"), 502
    except RuntimeError:
        return jsonify(ok=False, error="BACKEND_BAD_RESPONSE"), 502

    return jsonify(data), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
