"""Boots the Wayward FastAPI backend inside the Android app.

Called once from WaywardApp on a background thread with the path of the
extracted repo tree (server/ + client/dist). Blocks forever serving uvicorn
on 127.0.0.1:8000; the WebView is the only client.
"""

import os
import sys

_started = False


def start(app_root: str) -> None:
    global _started
    if _started:
        return
    _started = True

    os.environ.setdefault(
        "WAYWARD_CLIENT_DIST", os.path.join(app_root, "client", "dist")
    )
    os.chdir(app_root)
    if app_root not in sys.path:
        sys.path.insert(0, app_root)

    import uvicorn

    from server.main import app

    config = uvicorn.Config(
        app, host="127.0.0.1", port=8000, log_level="info", workers=1
    )
    # uvicorn skips signal-handler installation off the main thread, so
    # Server.run() is safe from this worker thread.
    uvicorn.Server(config).run()
