"""
ASGI entry point for Fly.io: wraps server.py's MCP app with an api_key auth
gate, mirroring the proxy.cjs pattern used by garmin-connect-mcp. server.py
itself is not modified.
"""

import os
import sys
from urllib.parse import parse_qsl

from starlette.responses import JSONResponse

from server import mcp

API_KEY = os.environ.get("API_KEY")
if not API_KEY:
    print("ERROR: API_KEY env var is required", file=sys.stderr)
    sys.exit(1)


class ApiKeyMiddleware:
    """Raw ASGI middleware (not BaseHTTPMiddleware) to avoid buffering streamed responses."""

    def __init__(self, app: object, api_key: str) -> None:
        self.app = app
        self.api_key = api_key

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        params = dict(parse_qsl(scope.get("query_string", b"").decode()))
        if params.get("api_key") != self.api_key:
            response = JSONResponse({"error": "Unauthorized"}, status_code=401)
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)


app = ApiKeyMiddleware(mcp.streamable_http_app(), API_KEY)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8080)
