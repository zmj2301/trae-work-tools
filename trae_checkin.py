"""TRAE Work daily sign-in via API. Runs on any machine (e.g. cloud server).

Uses the refresh-token + ExchangeToken flow to keep the access token alive,
then calls the checkin_credits/claim API to claim today's 200 Work credits.

Usage:
    python trae_checkin.py            # uses ./trae_config.json
    python trae_checkin.py -c path    # custom config path
    python trae_checkin.py --refresh  # force token refresh, then exit
"""
import argparse
import hashlib
import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests

try:
    from cryptography.hazmat.primitives import serialization, hashes
    from cryptography.hazmat.primitives.asymmetric import ec, utils as asym_utils
    HAVE_CRYPTO = True
except ImportError:
    HAVE_CRYPTO = False

BASE = Path(__file__).resolve().parent
LOG_FILE = BASE / "trae_checkin.log"


def log(msg):
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def load_config(path):
    cfg = json.load(open(path, encoding="utf-8"))
    if not cfg.get("refresh_token"):
        raise SystemExit("config missing refresh_token")
    return cfg


def save_config(path, cfg):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def device_info(cfg):
    """Build DeviceInfo object for ExchangeToken (must match registered device)."""
    return {
        "DeviceID": cfg.get("device_id", ""),
        "MachineID": cfg.get("machine_id", ""),
        "PlatformCode": cfg.get("platform_code", "SOLO_PC"),
        "DeviceType": cfg.get("device_type", "PC"),
        "DeviceName": cfg.get("device_name", ""),
        "DeviceModel": cfg.get("device_model", ""),
        "ClientVersion": cfg.get("app_version", ""),
        "DevicePublicKey": cfg.get("public_key_pem", ""),
        "DeviceBrand": cfg.get("device_brand", ""),
        "DeviceCPU": cfg.get("device_cpu", ""),
        "OSInfo": cfg.get("os_info", ""),
        "OSVersion": cfg.get("os_version", ""),
    }


def sign_data(private_pem, payload):
    """ECDSA-SHA256 signature over payload bytes (DER), base64."""
    key = serialization.load_pem_private_key(private_pem.encode(), password=None)
    sig = key.sign(payload, ec.ECDSA(hashes.SHA256()))
    return __import__("base64").b64encode(sig).decode()


def exchange_token(cfg, old_token=""):
    """Exchange refresh token for a fresh access token."""
    if not HAVE_CRYPTO:
        raise SystemExit("cryptography lib required for token refresh")
    host = cfg["host"].rstrip("/")
    client_id = cfg["client_id"]
    refresh_token = cfg["refresh_token"]
    path = "/trae/api/v3/oauth/ExchangeToken"
    url = host + path

    timestamp = int(time.time())
    nonce = hashlib.sha256(os.urandom(32)).hexdigest()[:32]
    to_sign = f"POST\n{path}\n{client_id}\n{refresh_token}\n{timestamp}\n{nonce}"
    signature = sign_data(cfg["private_key_pem"], to_sign.encode())

    body = {
        "ClientID": client_id,
        "ClientSecret": "",
        "RefreshToken": refresh_token,
        "DeviceInfo": device_info(cfg),
        "DeviceProof": {"Signature": signature, "Timestamp": timestamp, "Nonce": nonce},
        "IDEVersion": cfg.get("app_version", ""),
    }
    headers = {
        "Content-Type": "application/json",
        "x-cloudide-token": old_token,
    }
    r = requests.post(url, json=body, headers=headers, timeout=30)
    try:
        data = r.json()
    except Exception:
        data = {"raw": r.text}
    return r.status_code, data


def api_request(cfg, path, token, body=None):
    url = cfg["host"].rstrip("/") + path
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Cloud-IDE-JWT {token}",
        "x-device-id": cfg.get("device_id", ""),
    }
    return requests.post(url, json=body or {}, headers=headers, timeout=30)


def send_serverchan(cfg, title, desp):
    """Push a message to the user's phone via Server酱 (free)."""
    key = cfg.get("server_key")
    if not key:
        return
    try:
        r = requests.post(
            f"https://sctapi.ftqq.com/{key}.send",
            data={"title": title, "desp": desp},
            timeout=20,
        )
        ok = "error" in r.text and "SUCCESS" in r.text
        log(f"serverchan push {'ok' if ok else 'fail'}: HTTP {r.status_code}")
    except Exception as e:
        log(f"serverchan push error: {e}")


def write_pc_notice(cfg, message):
    """Write a notice file the PC-side script pulls and shows as a toast."""
    try:
        (BASE / "pc_notice.txt").write_text(message, encoding="utf-8")
        log("pc notice written")
    except Exception as e:
        log(f"pc notice error: {e}")


def notify(cfg, title, desp):
    """Send the same message to both phone (Server酱) and PC (notice file)."""
    send_serverchan(cfg, title, desp)
    write_pc_notice(cfg, title + "\n" + desp)


def fetch_credit_usage(cfg, token):
    """Fetch usage-credit (consumption) info and return a readable summary.

    Calls POST {host}/trae/api/v2/pay/ide_user_ent_usage which returns a list of
    entitlement packs; each pack has quota.credits_limit (total) and
    usage.credits_amount (consumed). Only packs with actual usage are listed.
    """
    try:
        r = api_request(cfg, "/trae/api/v2/pay/ide_user_ent_usage", token,
                        body={"require_usage": True, "req_source": 2})
        d = r.json()
        if d.get("code") not in (None, 0):
            log(f"credit usage fetch failed: {d}")
            return None
        packs = d.get("user_entitlement_pack_list") or []
        total_limit = 0.0
        total_used = 0.0
        lines = []
        for p in packs:
            bi = p.get("entitlement_base_info") or {}
            q = bi.get("quota") or {}
            us = p.get("usage") or {}
            try:
                limit = float(q.get("credits_limit") or 0)
            except (TypeError, ValueError):
                limit = 0.0
            try:
                used = float(us.get("credits_amount") or 0)
            except (TypeError, ValueError):
                used = 0.0
            total_limit += limit
            total_used += used
            if used > 0:
                name = p.get("display_desc") or p.get("group_name") or "权益"
                lines.append(f"{name}: 总额{limit:.1f} / 已耗{used:.1f} / 余{(limit-used):.1f}")
        if not packs:
            return None
        summary = f"用量积分：总额{total_limit:.1f} / 已消耗{total_used:.1f} / 剩余{max(total_limit-total_used,0):.1f}"
        if lines:
            summary += "\n" + "\n".join(lines)
        remaining = max(total_limit - total_used, 0)
        return summary, total_used, remaining
    except Exception as e:
        log(f"credit usage error: {e}")
        return None, None, None


def _day_bounds(days_ago=0):
    """Return (start_ts, end_ts) seconds covering one calendar day (local)."""
    d = datetime.now() - timedelta(days=days_ago)
    day_start = datetime(d.year, d.month, d.day, 0, 0, 0)
    day_end = datetime(d.year, d.month, d.day, 23, 59, 59)
    return int(day_start.timestamp()), int(day_end.timestamp())


def fetch_daily_session_usage(cfg, token, days_ago=0):
    """Fetch today's (or a past day's) per-session credit consumption.

    Uses the same API as the trae.cn dashboard usage page:
    POST /trae/api/v1/pay/query_user_usage_group_by_session with
    usage_type=[7]. Returns (total_credits, session_count, lines) where lines is
    a list of per-session summaries. Returns (None, 0, []) on failure.
    """
    start_ts, end_ts = _day_bounds(days_ago)
    try:
        page = 1
        total_credits = 0.0
        sessions = []
        while True:
            body = {
                "start_time": start_ts,
                "end_time": end_ts,
                "page_size": 20,
                "page_num": page,
                "usage_type": [7],
            }
            r = api_request(cfg, "/trae/api/v1/pay/query_user_usage_group_by_session",
                            token, body=body)
            d = r.json()
            page_sess = d.get("user_usage_group_by_sessions") or []
            sessions.extend(page_sess)
            for s in page_sess:
                try:
                    total_credits += float(s.get("credits_float") or 0)
                except (TypeError, ValueError):
                    pass
            total = d.get("total") or 0
            if page * 20 >= total or not page_sess or page > 10:
                break
            page += 1
        lines = []
        for s in sessions:
            c = s.get("credits_float") or 0
            model = s.get("model_name") or "?"
            t = s.get("usage_time") or 0
            tm = datetime.fromtimestamp(t).strftime("%H:%M") if t else ""
            prev = (s.get("user_input_preview") or "").strip().replace("\n", " ")
            if len(prev) > 24:
                prev = prev[:24] + "…"
            lines.append(f"{tm} {model} +{c} {prev}")
        return round(total_credits, 2), len(sessions), lines
    except Exception as e:
        log(f"daily session usage error: {e}")
        return None, 0, []


def check_daily_consumption(cfg, today_credits):
    """Raise a PC high-priority alert when today's precise consumption exceeds
    the configured threshold.

    today_credits comes from the dashboard per-session API (exact, not inferred
    from cumulative deltas). Writes pc_alert.txt (pulled by trae_remind_pc.py).
    Returns today_credits or None if unavailable.
    """
    if today_credits is None:
        log("daily consumption unavailable, skipping alert check")
        return None
    try:
        threshold = float(cfg.get("daily_consumption_alert_threshold", 200) or 200)
        alert_file = BASE / "pc_alert.txt"
        if today_credits > threshold:
            msg = (f"\u26a0 \u4eca\u65e5\u6d88\u8017\u79ef\u5206\u5f02\u5e38\uff1a"
                   f"\u5f53\u65e5\u6d88\u8017 {today_credits:.1f}\uff08\u9608\u503c{threshold:.0f}\uff09\u3002")
            (BASE / "pc_alert.txt").write_text(msg, encoding="utf-8")
            log(f"ALERT: daily consumption {today_credits:.1f} > threshold {threshold:.0f}")
        else:
            log(f"daily consumption {today_credits:.1f} within threshold {threshold:.0f}")
            if alert_file.exists():
                alert_file.unlink()
        return today_credits
    except Exception as e:
        log(f"daily consumption check error: {e}")
        return None


def write_reminder(cfg):
    """Write a reminder file when the refresh token is close to expiry.

    The cloud server has no way to reach the user's home PC directly (dynamic IP /
    NAT), so it just drops a marker file. A small script on the user's PC pulls it
    and shows a desktop notification. Returns days-remaining or None if fine.
    """
    try:
        exp = cfg.get("refresh_expired_at")
        if not exp:
            return None
        dt = datetime.fromisoformat(exp.replace("Z", "+00:00"))
        remain = (dt - datetime.now(dt.tzinfo)).days
        remind_file = BASE / "refresh_reminder.txt"
        if remain <= 30:
            remind_file.write_text(
                f"TRAE refresh token expires in {remain} days ({exp}). "
                f"Re-run make_config.py on Windows to renew.\n",
                encoding="utf-8",
            )
            log(f"WARNING: refresh token expires in {remain} days, reminder written")
            return remain
        else:
            if remind_file.exists():
                remind_file.unlink()
            return None
    except Exception as e:
        log(f"reminder check skipped: {e}")
        return None


def get_valid_token(cfg):
    """Return a working access token, refreshing if needed."""
    tok = cfg.get("access_token", "")
    if tok:
        # quick check
        r = api_request(cfg, "/trae/api/v2/ug/checkin_credits/status", tok)
        try:
            if r.json().get("code") == 0:
                return tok
        except Exception:
            pass
    log("access token invalid/expired, refreshing...")
    code, data = exchange_token(cfg, cfg.get("access_token", ""))
    result = (data or {}).get("Result") or {}
    if code != 200 or not result.get("Token"):
        log(f"token refresh failed: HTTP {code} -> {data}")
        raise SystemExit("could not refresh token")
    cfg["access_token"] = result["Token"]
    if result.get("RefreshToken"):
        cfg["refresh_token"] = result["RefreshToken"]
    if result.get("TokenExpireAt"):
        cfg["token_expired_at"] = result["TokenExpireAt"]
    save_config(BASE / "trae_config.json", cfg)
    log("token refreshed")
    return cfg["access_token"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-c", "--config", default=str(BASE / "trae_config.json"))
    parser.add_argument("--refresh", action="store_true", help="only refresh token")
    parser.add_argument("--test", action="store_true",
                        help="send a test push to phone+PC, no real check-in")
    args = parser.parse_args()

    cfg = load_config(args.config)
    cfg["host"] = cfg.get("host") or "https://api.trae.cn"

    if args.test:
        token = get_valid_token(cfg)
        usage, total_used, remaining = fetch_credit_usage(cfg, token)
        today_used, n_sess, sess_lines = fetch_daily_session_usage(cfg, token)
        check_daily_consumption(cfg, today_used)
        body = "这是一条测试消息。\n若你收到说明推送链路正常。\n\n"
        if today_used is not None:
            body += f"今日消耗：{today_used:.1f}（{n_sess} 会话）\n"
        body += (usage or "用量积分获取失败")
        notify(cfg, "TRAE 测试通知", body)
        log("test push sent")
        return

    token = get_valid_token(cfg)

    if args.refresh:
        log("refresh done, token valid")
        return

    write_reminder(cfg)

    usage, total_used, remaining = fetch_credit_usage(cfg, token)
    if usage:
        log(usage)
    today_used, n_sess, sess_lines = fetch_daily_session_usage(cfg, token)
    check_daily_consumption(cfg, today_used)

    # check status
    r = api_request(cfg, "/trae/api/v2/ug/checkin_credits/status", token)
    try:
        st = r.json()
    except Exception:
        log(f"status bad response HTTP {r.status_code}: {r.text[:200]}")
        return
    if st.get("code") != 0:
        log(f"status failed: {st}")
        return

    checked_in = st.get("checked_in")
    credits = st.get("credits")
    log(f"today checked_in={checked_in}, credits={credits}")

    daily = f"今天已签到，Work 积分：{credits}"
    if today_used is not None:
        daily += f"\n今日消耗：{today_used:.1f}（{n_sess} 个会话）"
    if usage:
        daily += "\n" + usage
    if sess_lines:
        daily += "\n最近会话消耗：" + "\n".join(sess_lines[:3])

    if checked_in:
        log("already checked in today, nothing to do")
        notify(cfg, "TRAE 今日已签到", daily)
        return

    # claim
    r = api_request(cfg, "/trae/api/v2/ug/checkin_credits/claim", token)
    try:
        cl = r.json()
    except Exception:
        log(f"claim bad response HTTP {r.status_code}: {r.text[:200]}")
        notify(cfg, "TRAE 签到失败", f"领取积分响应异常 HTTP {r.status_code}，请检查服务器日志。")
        return
    if cl.get("code") == 0:
        log("SIGN-IN SUCCESS (claimed 200 Work credits)")
        notify(cfg, "TRAE 签到成功", f"成功领取 200 Work 积分！\n" + daily)
    else:
        log(f"claim failed: {cl}")
        notify(cfg, "TRAE 签到失败", f"领取积分失败：{cl}")


if __name__ == "__main__":
    main()
