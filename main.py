"""
Entry point — khởi tạo app và mount routers.
"""

import asyncio
import logging
import os
import shutil
import traceback
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.database import init_db
from app.routers import chat, admin, zalo, push

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ──────────────────────────────────────────────
    data_dir = Path("data")
    data_dir.mkdir(exist_ok=True)

    seed_dir = Path("data_seed")
    if seed_dir.exists() and not any(data_dir.glob("*.md")):
        for f in seed_dir.glob("*.md"):
            shutil.copy(f, data_dir / f.name)
        logging.info("Copied seed knowledge base to data/")

    init_db()

    from app.services.embeddings import EMBED_ENABLED, index_document, get_indexed_sources
    if EMBED_ENABLED:
        indexed  = get_indexed_sources()
        to_index = [f for f in data_dir.glob("*.md") if f.stem not in indexed]
        if to_index:
            logging.info("Auto-indexing %d file(s)...", len(to_index))
            for f in to_index:
                try:
                    await index_document(f.stem, f.stem.replace("_", " ").title(),
                                         f.read_text(encoding="utf-8"))
                except Exception as e:
                    logging.error("Index lỗi %s: %s", f.name, e)
            logging.info("Auto-index hoàn tất.")

    # ── Evolution Engine ─────────────────────────────────────
    from app.services.evolution import evolution_scheduler
    _evo_task = asyncio.create_task(evolution_scheduler())

    yield

    # ── Shutdown ─────────────────────────────────────────────
    _evo_task.cancel()
    try:
        await _evo_task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="Chatbot Cà Chua", version="2.0.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")

app.include_router(chat.router)
app.include_router(admin.router)
app.include_router(zalo.router)
app.include_router(push.router)


log = logging.getLogger("app.errors")


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Bắt tất cả lỗi 500 không xử lý được — log + notify admin qua Telegram."""
    tb_lines = traceback.format_exception(type(exc), exc, exc.__traceback__)
    tb_short  = "".join(tb_lines[-5:]).strip()  # 5 dòng cuối của traceback
    detail    = f"{type(exc).__name__}: {str(exc)[:300]}"

    log.error("Unhandled exception [%s %s]\n%s", request.method, request.url.path, "".join(tb_lines))

    from app.services.notify import push
    await push(
        kind="error",
        title=f"{request.method} {request.url.path} — {type(exc).__name__}",
        reason=f"{str(exc)[:200]}\n\n{tb_short[:400]}",
    )

    return JSONResponse(
        status_code=500,
        content={"error": "server_error", "detail": "Lỗi server không xác định. Admin đã được thông báo tự động."},
    )


@app.get("/")
async def index(request: Request):
    resp = FileResponse("static/index.html")
    if not request.cookies.get("did"):
        resp.set_cookie(
            "did",
            str(uuid.uuid4()),
            max_age=365 * 24 * 3600,  # 1 năm
            httponly=True,
            samesite="lax",
        )
    return resp


@app.get("/health")
async def health():
    from app.services.rag import rag
    return {"status": "ok", "chunks": rag.chunk_count}


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
