"""
ASGI entry point for Fly.io: wraps server.py's MCP app with an api_key auth
gate, mirroring the proxy.cjs pattern used by garmin-connect-mcp. server.py
itself is not modified.

Also exposes a one-off /admin/upload/{filename} endpoint (gated by the same
api_key) to seed the Fly volume with Parquet files over plain HTTPS, since
SSH/SFTP tunnels to Fly are blocked on this network. Remove once data is loaded.
"""

import os
import sys
from pathlib import Path
from urllib.parse import parse_qsl

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Mount, Route

from server import mcp

API_KEY = os.environ.get("API_KEY")
if not API_KEY:
    print("ERROR: API_KEY env var is required", file=sys.stderr)
    sys.exit(1)

DATA_DIR = Path(os.environ.get("APPLE_HEALTH_DATA_DIR", "/data"))


async def upload_file(request: Request) -> PlainTextResponse:
    if request.query_params.get("api_key") != API_KEY:
        return PlainTextResponse("Unauthorized", status_code=401)
    filename = request.path_params["filename"]
    if "/" in filename or "\\" in filename or filename.startswith("."):
        return PlainTextResponse("Invalid filename", status_code=400)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    dest = DATA_DIR / filename
    size = 0
    with open(dest, "wb") as f:
        async for chunk in request.stream():
            f.write(chunk)
            size += len(chunk)
    return PlainTextResponse(f"Saved {filename} ({size} bytes)")


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


base_app = Starlette(routes=[
    Route("/admin/upload/{filename}", upload_file, methods=["PUT"]),
    Mount("/", app=mcp.streamable_http_app()),
])

app = ApiKeyMiddleware(base_app, API_KEY)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8080)
