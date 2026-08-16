"""mitmproxy addon: log TRAE API traffic (hosts containing 'trae') to a file.
Run: mitmdump -s capture_addon.py -q
"""
import json
import time

LOG = r"C:\Users\ZHOUy\Desktop\coing\trae_capture.jsonl"


def request(flow):
    host = flow.request.pretty_host or ""
    if "trae" not in host and "byte" not in host and "byted" not in host:
        return
    rec = {
        "ts": time.time(),
        "method": flow.request.method,
        "url": flow.request.url,
        "host": host,
    }
    ct = flow.request.headers.get("content-type", "")
    if flow.request.method == "POST":
        try:
            rec["body"] = flow.request.get_text()
        except Exception:
            rec["body"] = None
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def response(flow):
    host = flow.request.pretty_host or ""
    if "trae" not in host and "byte" not in host and "byted" not in host:
        return
    with open(LOG, "a", encoding="utf-8") as f:
        body = None
        try:
            body = flow.response.get_text()
        except Exception:
            body = None
        rec = {
            "ts": time.time(),
            "type": "resp",
            "url": flow.request.url,
            "status": flow.response.status_code,
            "content_type": flow.response.headers.get("content-type", ""),
            "body_preview": (body or "")[:2000],
        }
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")