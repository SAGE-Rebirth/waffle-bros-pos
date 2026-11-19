"""`uv run waffle-pos` - start the POS server."""

import socket

import uvicorn

from waffle_pos.app import create_app
from waffle_pos.config import get_config


def _lan_ip() -> str | None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))  # no packet is sent; picks the outward interface
            ip: str = s.getsockname()[0]
            return ip
    except OSError:
        return None


def main() -> None:
    config = get_config()
    print(f"\n  Waffle Bros POS\n  On this computer:   http://localhost:{config.port}")
    if ip := _lan_ip():
        print(f"  On the shop Wi-Fi:  http://{ip}:{config.port}  (tablet / phone)")
    print(
        f"  Data file:          {config.db_path}\n  API docs:           http://localhost:{config.port}/docs\n"
    )
    uvicorn.run(
        create_app(config),
        host=config.host,
        port=config.port,
        log_level="warning",
        proxy_headers=True,
        forwarded_allow_ips=config.forwarded_allow_ips,
    )


if __name__ == "__main__":
    main()
