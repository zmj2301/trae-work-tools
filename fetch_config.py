"""Fetch the ready-made trae_config.json from the cloud server over SSH.

On a new computer, instead of logging into TRAE Work and re-extracting your
credentials (make_config.py), just download the config that is already running
on the server:

    set TRAE_SERVER_PASS=your_server_password
    python fetch_config.py

Reads SSH settings from environment variables (falling back to the default
server). The password is NEVER hardcoded here or committed.

Environment:
    TRAE_SERVER_HOST   (default 39.107.96.165)
    TRAE_SERVER_USER   (default root)
    TRAE_SERVER_PORT   (default 22)
    TRAE_SERVER_PASS   (required; SSH password)
    TRAE_CONFIG_REMOTE (default /opt/trae_checkin/trae_config.json)
"""
import os
import sys

import paramiko


def main():
    host = os.environ.get("TRAE_SERVER_HOST", "39.107.96.165")
    user = os.environ.get("TRAE_SERVER_USER", "root")
    port = int(os.environ.get("TRAE_SERVER_PORT", "22"))
    password = os.environ.get("TRAE_SERVER_PASS")
    remote = os.environ.get("TRAE_CONFIG_REMOTE", "/opt/trae_checkin/trae_config.json")
    local = os.environ.get("TRAE_CONFIG_LOCAL", "trae_config.json")

    if not password:
        print("ERROR: TRAE_SERVER_PASS is not set.", file=sys.stderr)
        print("  PowerShell:  $env:TRAE_SERVER_PASS='your_password'", file=sys.stderr)
        print("  CMD:         set TRAE_SERVER_PASS=your_password", file=sys.stderr)
        sys.exit(1)

    print(f"Connecting to {user}@{host}:{port} ...")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(host, port=port, username=user, password=password, timeout=20)

    sftp = c.open_sftp()
    try:
        sftp.get(remote, local)
    except IOError as e:
        print(f"ERROR: could not download {remote}: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        sftp.close()
        c.close()

    print(f"OK: saved to {local}")
    print("Now you can run: python trae_checkin.py --test")


if __name__ == "__main__":
    main()