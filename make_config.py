"""Generate trae_config.json from local TRAE Work storage.

Run this ONCE on the Windows machine (where you're logged in). It extracts the
refresh token, device key pair, and device info needed to sign in from the
cloud server. The refresh token lasts ~6 months and can renew itself.

WARNING: trae_config.json contains your credentials. Keep it private.
"""
import json
import base64
from pathlib import Path

from trae_token import load_auth_info, find_storage_json

OUT = Path(__file__).parent / "trae_config.json"
STORAGE_JSON = Path(find_storage_json())


def get_machine_id():
    store = json.load(open(STORAGE_JSON, encoding="utf-8"))
    return store.get("telemetry.machineId", "")


def main():
    info = load_auth_info()

    auth = None
    for k, v in info.items():
        if k.endswith("icube.cloudide"):
            auth = json.loads(v.strip("\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b\x0c\x0d\x0e\x0f\x10"))
            break
    if not auth:
        raise SystemExit("No auth info found")

    device = None
    for k, v in info.items():
        if "icube-dc:" in k:
            device = json.loads(v.strip("\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b\x0c\x0d\x0e\x0f\x10"))
            break

    host = auth.get("host", "https://api.trae.cn")
    device_id = None
    for k in info:
        if "icube-dc:" in k:
            device_id = k.rsplit(":", 1)[-1]
            break

    old_cfg = {}
    if OUT.exists():
        try:
            old_cfg = json.loads(OUT.read_text(encoding="utf-8"))
        except Exception:
            pass

    cfg = {
        "host": host,
        "device_id": device_id,
        "machine_id": get_machine_id(),
        "client_id": "en1oxy7wnw8j9n",
        "app_version": "0.1.48",
        # Device info that matches what the server registered for this device.
        "platform_code": "SOLO_PC",
        "device_type": "PC",
        "device_name": "ZHOUy的电脑",
        "device_model": "83QH",
        "device_brand": "LENOVO",
        "device_cpu": "AMD Ryzen 7 H 255 w/ Radeon 780M Graphics",
        "os_info": "windows",
        "os_version": "Windows 11 Home China",
        "refresh_token": auth.get("refreshToken"),
        "access_token": auth.get("token"),
        "token_expired_at": auth.get("expiredAt"),
        "refresh_expired_at": auth.get("refreshExpiredAt"),
        "private_key_pem": (device or {}).get("privateKeyPEM"),
        "public_key_pem": (device or {}).get("publicKeyPEM"),
        # Preserved values (not from auth): keep existing ones if present.
        "server_key": old_cfg.get("server_key", ""),
        "daily_consumption_alert_threshold": old_cfg.get("daily_consumption_alert_threshold", 200),
    }
    OUT.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Wrote", OUT)
    print("device_id:", device_id)
    print("machine_id:", cfg["machine_id"])


if __name__ == "__main__":
    main()
