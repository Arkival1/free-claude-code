"""Let FCC Phone, served from another origin, call the phone paths.

Only /studio/api/phone/ answers other origins. Those paths need a pairing
code or the phone's own secret in an Authorization header, and never a
cookie, so a web page the phone app did not write can't use them.
"""

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

PHONE_PREFIX = "/studio/api/phone/"
_HEADERS = {
    "access-control-allow-origin": "*",
    "access-control-allow-methods": "GET, POST, OPTIONS",
    "access-control-allow-headers": "authorization, content-type",
    "access-control-max-age": "600",
}


class PhoneCorsMiddleware:
    """Answer preflights and add CORS headers on the phone paths only."""

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope.get("path", "").startswith(
            PHONE_PREFIX
        ):
            await self._app(scope, receive, send)
            return
        if scope.get("method") == "OPTIONS":
            await send(
                {
                    "type": "http.response.start",
                    "status": 204,
                    "headers": [
                        (key.encode(), value.encode())
                        for key, value in _HEADERS.items()
                    ],
                }
            )
            await send({"type": "http.response.body", "body": b""})
            return

        async def send_with_cors(message: Message) -> None:
            if message["type"] == "http.response.start":
                message = dict(message)
                raw_headers = list(message.get("headers", ()))
                headers = MutableHeaders(raw=raw_headers)
                for key, value in _HEADERS.items():
                    headers[key] = value
                message["headers"] = raw_headers
            await send(message)

        await self._app(scope, receive, send_with_cors)
