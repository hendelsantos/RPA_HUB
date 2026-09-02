from __future__ import annotations

import argparse
import platform
import socket
import time

import requests


def main() -> None:
    parser = argparse.ArgumentParser(description="Worker local do HUB RPA.")
    parser.add_argument("--hub", default="http://127.0.0.1:8010")
    parser.add_argument("--name", default=socket.gethostname())
    parser.add_argument("--machine-id", default=f"{socket.gethostname()}-{platform.system()}")
    parser.add_argument("--tags", default=f"{platform.system().lower()},local,playwright")
    parser.add_argument("--interval", type=int, default=20)
    args = parser.parse_args()

    tags = [tag.strip() for tag in args.tags.split(",") if tag.strip()]
    response = requests.post(
        f"{args.hub}/workers/register",
        json={"name": args.name, "machine_id": args.machine_id, "tags": tags, "max_concurrent_runs": 1},
        timeout=10,
    )
    response.raise_for_status()
    worker = response.json()
    print(f"Worker registrado: {worker['id']} - {worker['name']}")

    while True:
        requests.post(f"{args.hub}/workers/{worker['id']}/heartbeat", json={"status": "online"}, timeout=10).raise_for_status()
        print("Heartbeat enviado")
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
