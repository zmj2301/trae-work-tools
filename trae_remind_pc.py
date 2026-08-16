"""Windows-side pull script: fetches TRAE notifications from the cloud server
and shows a desktop toast.

Run this periodically (e.g. via Task Scheduler every 6h). It pulls:
  - pc_alert.txt        HIGH-PRIORITY: daily credit consumption over threshold.
                        Always shown (no dedupe), prominent style, then deleted.
  - pc_notice.txt       written after each sign-in attempt (success/failure)
  - refresh_reminder.txt written when the refresh token is within 30 days of expiry

Requires: paramiko (pip install paramiko)
"""
from pathlib import Path

import paramiko

BASE = Path(__file__).resolve().parent
MARKER = BASE / "last_reminder_seen.txt"

# SSH to the cloud server (edit these)
SERVER_HOST = "39.107.96.165"
SERVER_PORT = 22
SERVER_USER = "root"
SERVER_PASSWORD = "ZHOUmj32842510*"
ALERT_FILE = "/opt/trae_checkin/pc_alert.txt"
REMOTE_FILES = [
    "/opt/trae_checkin/pc_notice.txt",
    "/opt/trae_checkin/refresh_reminder.txt",
]


def _connect():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(SERVER_HOST, port=SERVER_PORT, username=SERVER_USER,
              password=SERVER_PASSWORD, timeout=15)
    return c


def fetch_alert():
    """Return alert content (or '') and whether it existed. High priority."""
    c = _connect()
    sftp = c.open_sftp()
    content = ""
    exists = False
    try:
        with sftp.open(ALERT_FILE, "r") as f:
            content = f.read().decode("utf-8", errors="replace").strip()
        exists = True
    except IOError:
        pass
    sftp.close()
    c.close()
    return content, exists


def delete_alert():
    c = _connect()
    sftp = c.open_sftp()
    try:
        sftp.remove(ALERT_FILE)
    except IOError:
        pass
    sftp.close()
    c.close()


def fetch_files():
    c = _connect()
    sftp = c.open_sftp()
    contents = {}
    for path in REMOTE_FILES:
        try:
            with sftp.open(path, "r") as f:
                contents[path] = f.read().decode("utf-8", errors="replace").strip()
        except IOError:
            contents[path] = ""
    sftp.close()
    c.close()
    return contents


def show_notification(title, message, priority=False):
    if priority:
        try:
            import winsound
            winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
        except Exception:
            pass
    try:
        from plyer import notification
        notification.notify(title=title, message=message,
                            timeout=30 if priority else 15,
                            app_name="TRAE")
        return True
    except Exception:
        pass
    try:
        (BASE / "reminder.txt").write_text(message, encoding="utf-8")
    except Exception:
        pass
    print("NOTIFY:", title, "-", message)
    return False


def main():
    # 1. High-priority alert: always show, then delete (once per day).
    alert, alert_exists = fetch_alert()
    if alert_exists and alert:
        show_notification("\u26a0 TRAE \u79ef\u5206\u5f02\u5e38\u6d88\u8017", alert, priority=True)
        delete_alert()
        print("alert shown")
        return

    # 2. Normal notices with dedupe.
    contents = fetch_files()
    last = MARKER.read_text(encoding="utf-8").strip() if MARKER.exists() else ""
    payload = None
    for path in REMOTE_FILES:
        if contents.get(path):
            payload = contents[path]
            break

    if payload and payload != last:
        title = "TRAE 提醒"
        if "expires in" in payload:
            title = "TRAE 登录凭证即将过期"
        elif "签到" in payload:
            title = "TRAE 签到结果"
        show_notification(title, payload)
        MARKER.write_text(payload, encoding="utf-8")
        print("notification shown")
    else:
        print("no new notification")


if __name__ == "__main__":
    main()