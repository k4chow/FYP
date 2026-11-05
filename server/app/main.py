from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .import_jobs import recover_import_jobs
from .routers import auth, conversations, films, imports, memories, profile


@asynccontextmanager
async def lifespan(_: FastAPI):
    recover_import_jobs()
    yield


app = FastAPI(title="NOACF API", version="0.5.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(films.router, prefix="/films", tags=["films"])
app.include_router(imports.router, prefix="/import", tags=["import"])
app.include_router(
    conversations.router, prefix="/conversations", tags=["conversations"]
)
app.include_router(memories.router, prefix="/memories", tags=["memories"])
app.include_router(profile.router, prefix="/profile", tags=["profile"])


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "noacf-api", "version": app.version}
