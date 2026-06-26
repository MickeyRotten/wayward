import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# Route all "wayward.*" logs to the terminal (stdout) for easy troubleshooting,
# independently of uvicorn's own logging config. Force UTF-8 first so prompt
# text with em-dashes / non-ASCII doesn't raise encode errors on Windows.
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

_wlog = logging.getLogger("wayward")
if not _wlog.handlers:
    _handler = logging.StreamHandler(sys.stdout)
    _handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s | %(message)s", "%H:%M:%S"))
    _wlog.addHandler(_handler)
    _wlog.setLevel(logging.INFO)
    _wlog.propagate = False

from server.api.routes import router

PORTRAITS_DIR = Path(__file__).resolve().parent / "portraits"
PORTRAITS_DIR.mkdir(exist_ok=True)
from server.db.database import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Resolve/attach the active campaign+adventure (migrates a legacy wayward.db
    # or seeds a fresh default scope on first run).
    await init_db()
    yield


app = FastAPI(title="Wayward", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(router)
app.mount("/portraits", StaticFiles(directory=str(PORTRAITS_DIR)), name="portraits")


@app.get("/health")
async def health():
    return {"status": "ok"}
