"""Stamp Bojot — API FastAPI. Jalankan: uvicorn app.main:app --reload"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import config
from .db import bootstrap, get_db
from .routers import admin, metrics, public
from .services.jobs import build_scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")

STATIC_DIR = os.environ.get("STATIC_DIR", os.path.join(os.path.dirname(__file__), "..", "static"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    db = get_db()
    await bootstrap(db)
    scheduler = None
    if config.enable_scheduler:
        scheduler = build_scheduler()
        scheduler.start()
        log.info("Scheduler aktif (WIB).")
    yield
    if scheduler:
        scheduler.shutdown(wait=False)


app = FastAPI(title=config.app_name, version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in config.cors_origins.split(",")] if config.cors_origins != "*" else ["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    first = exc.errors()[0] if exc.errors() else {}
    loc = ".".join(str(p) for p in first.get("loc", []) if p != "body")
    return JSONResponse(422, {"detail": {"code": "validation", "message": f"Data belum lengkap atau tidak valid ({loc})."}})


app.include_router(public.router)
app.include_router(admin.router)
app.include_router(metrics.router)


@app.get("/api/health")
async def health():
    return {"ok": True, "app": config.app_name}


# Serve frontend build (single container) bila folder static ada; fallback ke index.html untuk SPA routing
if os.path.isdir(STATIC_DIR):
    app.mount("/assets", StaticFiles(directory=os.path.join(STATIC_DIR, "assets")), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str):
        candidate = os.path.join(STATIC_DIR, full_path)
        if full_path and os.path.isfile(candidate):
            return FileResponse(candidate)
        return FileResponse(os.path.join(STATIC_DIR, "index.html"))
