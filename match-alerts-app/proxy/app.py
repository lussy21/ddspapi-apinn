import os
import json
import base64
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
VAPID_PRIVATE_KEY_B64 = os.environ.get("VAPID_PRIVATE_KEY_B64", "")
VAPID_SUBJECT = os.environ.get("VAPID_SUBJECT", "mailto:admin@dreamteamtips.gr")


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
def admin_page():
    return send_from_directory(APP_DIR, "admin.html")


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

    if payload.get("action") == "adminPushSend":
        title = str(payload.get("title") or "").strip()[:80]
        body = str(payload.get("body") or "").strip()[:220]
        admin_code = str(payload.get("adminCode") or "")
        if not title or not body:
            return jsonify(ok=False, error="BAD_PUSH_MESSAGE"), 200
        if not VAPID_PRIVATE_KEY_B64:
            return jsonify(ok=False, error="PUSH_NOT_CONFIGURED"), 500

        try:
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

        try:
            vapid_private_key = base64.b64decode(VAPID_PRIVATE_KEY_B64).decode("utf-8")
        except Exception:
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
