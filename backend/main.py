"""
AEGIS - Automated Expert Guidance & Intelligence System
Local FastAPI server - starts on http://127.0.0.1:7430
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from database import init_db
from routers import (
    collections, documents, search, ai, annotations, graph, audit, reports,
    conversations, profile, bias,
)
from cve_importer import cve_router

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    init_db()
    print("=" * 60)
    print("  AEGIS is running at  http://127.0.0.1:7430")
    print("  Open the above URL in your browser")
    print("=" * 60)
    yield
    # Shutdown (nothing needed)


app = FastAPI(
    title="AEGIS",
    description="Automated Expert Guidance & Intelligence System",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

# Allow the frontend (served on same origin) plus any local dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:7430", "http://localhost:7430",
                   "http://127.0.0.1:5173", "http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# API routers
app.include_router(collections.router)
app.include_router(documents.router)
app.include_router(search.router)
app.include_router(ai.router)
app.include_router(annotations.router)
app.include_router(graph.router)
app.include_router(audit.router)
app.include_router(reports.router)
app.include_router(conversations.router)
app.include_router(profile.router)
app.include_router(bias.router)
app.include_router(cve_router)


# Health check
@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "1.0.0"}


# Serve frontend (must come last - catch-all)
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str):
        index = FRONTEND_DIR / "index.html"
        if index.exists():
            return FileResponse(str(index))
        return {"error": "Frontend not found"}
