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
from .db import DB_STATUS, bootstrap, connect_or_fallback
from .routers import admin, metrics, public
from .services.jobs import build_scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")

STATIC_DIR = os.environ.get("STATIC_DIR", os.path.join(os.path.dirname(__file__), "..", "static"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    db = await connect_or_fallback()
    await bootstrap(db)
    if config.default_admin_pin == "1234":
        log.warning("DEFAULT_ADMIN_PIN masih 1234 — ganti sebelum pilot (PIN admin pertama dibuat dari nilai ini).")
    if config.metrics_api_key.startswith("ganti-"):
        log.warning("METRICS_API_KEY masih nilai bawaan — ganti sebelum integrasi dashboard lain.")
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
    return JSONResponse(status_code=422, content={"detail": {"code": "validation", "message": f"Data belum lengkap atau tidak valid ({loc})."}})


@app.exception_handler(Exception)
async def unhandled_handler(request: Request, exc: Exception):
    log.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": {"code": "server_error", "message": "Ada gangguan sebentar, coba lagi ya."}})


app.include_router(public.router)
app.include_router(admin.router)
app.include_router(metrics.router)


@app.get("/api/health")
async def health():
    """Status untuk monitoring; `db.persistent` harus true di produksi."""
    return {"ok": True, "app": config.app_name, "db": DB_STATUS}


# Serve frontend build (single container) bila folder static ada; fallback ke index.html untuk SPA routing
if os.path.isdir(STATIC_DIR):
    app.mount("/assets", StaticFiles(directory=os.path.join(STATIC_DIR, "assets")), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str):
        candidate = os.path.join(STATIC_DIR, full_path)
        if full_path and os.path.isfile(candidate):
            return FileResponse(candidate)
        return FileResponse(os.path.join(STATIC_DIR, "index.html"))
