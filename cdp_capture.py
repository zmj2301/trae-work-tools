"""CDP listener: capture TRAE web API requests (query_user_usage_group_by_session,
web_user_ent_usage, etc.) to trae_cdp_capture.json.
Run: python cdp_capture.py
"""
import asyncio
import json
import time

import websockets

CDP_WS = "ws://127.0.0.1:9222/devtools/browser/f79dae5e-62d9-4f30-9d59-dc11b51b8f31"
LOG = r"C:\Users\ZHOUy\Desktop\coing\trae_cdp_capture.jsonl"
TARGETS = ["query_user_usage", "web_user_ent_usage", "user_ent_usage",
           "billing_history", "pay_status"]
msg_id = 0


async def send(ws, method, params=None):
    global msg_id
    msg_id += 1
    await ws.send(json.dumps({"id": msg_id, "method": method, "params": params or {}}))
    return msg_id


async def main():
    async with websockets.connect(CDP_WS, max_size=2**27) as ws:
        await send(ws, "Target.setDiscoverTargets", {"discover": True})
        print("listening on browser target...", flush=True)

        async def drain():
            try:
                while True:
                    msg = json.loads(await ws.recv())
                    m = msg.get("method", "")
                    if m in ("Network.requestWillBeSent", "Network.responseReceived"):
                        req = msg.get("params", {}).get("request", {})
                        url = req.get("url", "")
                        if "trae" in url and ("pay" in url or "usage" in url):
                            rec = {
                                "ts": time.time(),
                                "type": m,
                                "url": url,
                                "method": req.get("method"),
                                "headers": {k: v for k, v in (req.get("headers") or {}).items()
                                            if k.lower() in ("authorization", "cookie", "content-type",
                                                             "x-device-id", "x-cloudide-token")},
                                "post_data": req.get("postData"),
                            }
                            with open(LOG, "a", encoding="utf-8") as f:
                                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            except asyncio.CancelledError:
                pass
            except Exception as e:
                print("drain err:", e, flush=True)

        task = asyncio.create_task(drain())
        try:
            await asyncio.sleep(3600)
        finally:
            task.cancel()


if __name__ == "__main__":
    asyncio.run(main())