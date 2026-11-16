"""CSRF guard (SPEC.md "Marketing and accounts", Sessions): every state-changing request must
carry an `X-Requested-With` header. A cross-site form or `fetch` can't add a custom header
without a CORS preflight, and CORS only allows the app's own origins, so a request that has it
came from the app. Pure ASGI, so SSE responses stream through untouched.
"""

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


class RequireXRequestedWith:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["method"] not in SAFE_METHODS:
            has_header = any(k == b"x-requested-with" and v for k, v in scope["headers"])
            if not has_header:
                response = JSONResponse(
                    {"detail": "Missing X-Requested-With header"}, status_code=403
                )
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)
