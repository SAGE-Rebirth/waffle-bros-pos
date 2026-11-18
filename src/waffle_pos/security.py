"""Small ASGI middlewares that harden the POS on the shop network.

* :class:`HostCheck` blocks DNS rebinding: a web page on the internet can't use a name it controls
  to reach this server from a browser on the shop Wi-Fi, because only IP addresses, single-word
  names (``localhost``, ``shop-pc``), ``*.local`` names and ``WB_ALLOWED_HOSTS`` are accepted.
* :class:`BodyLimit` refuses request bodies over a size limit before they are read into memory.
* :class:`SecurityHeaders` adds the usual browser protections (no framing, no MIME sniffing, a
  Content-Security-Policy for the screens).
"""

from __future__ import annotations

import ipaddress
import json
from collections.abc import Iterable

from starlette.types import ASGIApp, Message, Receive, Scope, Send

# The screens only load their own files; images may be inline data: URLs. Swagger UI (/docs)
# loads its script and styles from a CDN, so it gets its own, looser policy.
APP_CSP = (
    "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
    "script-src 'self'; connect-src 'self'; font-src 'self' data:; object-src 'none'; "
    "base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
)
DOCS_CSP = (
    "default-src 'self'; img-src 'self' data: https://fastapi.tiangolo.com; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; connect-src 'self'; "
    "object-src 'none'; frame-ancestors 'none'"
)
DOCS_PATHS = ("/docs", "/redoc")


async def _json_error(send: Send, status: int, message: str) -> None:
    body = json.dumps({"error": message}).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
        }
    )
    await send({"type": "http.response.body", "body": body})


def host_allowed(host: str, extra: Iterable[str] = ()) -> bool:
    name = host.strip().lower()
    if name.startswith("["):  # [IPv6]:port
        name = name[1 : name.find("]")] if "]" in name else name
    elif name.count(":") == 1:
        name = name.split(":")[0]
    if not name:
        return False
    try:
        ipaddress.ip_address(name)
        return True
    except ValueError:
        pass
    allowed = {h.strip().lower() for h in extra if h.strip()}
    return "." not in name or name.endswith(".local") or name in allowed


class HostCheck:
    def __init__(self, app: ASGIApp, extra_hosts: Iterable[str] = ()) -> None:
        self.app = app
        self.extra = tuple(extra_hosts)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            headers = dict(scope["headers"])
            host = headers.get(b"host", b"").decode("latin-1")
            if not host_allowed(host, self.extra):
                await _json_error(
                    send,
                    400,
                    "This address isn't allowed. Open the POS by its IP address or add the "
                    "name to WB_ALLOWED_HOSTS.",
                )
                return
        await self.app(scope, receive, send)


class BodyLimit:
    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope["headers"])
        length = headers.get(b"content-length")
        if length is not None and (not length.isdigit() or int(length) > self.max_bytes):
            await _json_error(send, 413, "The request is too large")
            return

        # Read the body up front (it's at most max_bytes), so an oversized chunked body gets a
        # clean 413 instead of reaching the app half-read.
        chunks: list[bytes] = []
        received = 0
        while True:
            message = await receive()
            if message["type"] != "http.request":
                return  # client went away
            body = message.get("body", b"")
            received += len(body)
            if received > self.max_bytes:
                await _json_error(send, 413, "The request is too large")
                return
            chunks.append(body)
            if not message.get("more_body", False):
                break

        replayed = False

        async def replay() -> Message:
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": b"".join(chunks), "more_body": False}
            return await receive()

        await self.app(scope, replay, send)


class SecurityHeaders:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path: str = scope.get("path", "")
        csp = DOCS_CSP if path.startswith(DOCS_PATHS) else APP_CSP

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers += [
                    (b"x-content-type-options", b"nosniff"),
                    (b"x-frame-options", b"DENY"),
                    (b"referrer-policy", b"no-referrer"),
                    (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
                    (b"content-security-policy", csp.encode()),
                ]
                if path.startswith("/api/"):
                    headers.append((b"cache-control", b"no-store"))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)
