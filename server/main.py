from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from server.api.routes import router

PORTRAITS_DIR = Path(__file__).resolve().parent / "portraits"
PORTRAITS_DIR.mkdir(exist_ok=True)
from server.db.database import create_tables
from server.db.seed import seed_defaults


@asynccontextmanager
async def lifespan(app: FastAPI):
    await create_tables()
    await seed_defaults()
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
