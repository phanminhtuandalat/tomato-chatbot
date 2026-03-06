"""
Entry point — khởi tạo app và mount routers.
"""

import logging
import os
import uuid

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.database import init_db
from app.routers import chat, admin, zalo, push

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

app = FastAPI(title="Chatbot Cà Chua", version="2.0.0")
app.mount("/static", StaticFiles(directory="static"), name="static")

app.include_router(chat.router)
app.include_router(admin.router)
app.include_router(zalo.router)
app.include_router(push.router)


@app.on_event("startup")
async def startup():
    import shutil
    from pathlib import Path
    data_dir = Path("data")
    data_dir.mkdir(exist_ok=True)
    # Nếu Volume mới toanh (chưa có .md) → copy knowledge base từ repo vào
    seed_dir = Path("data_seed")
    if seed_dir.exists() and not any(data_dir.glob("*.md")):
        for f in seed_dir.glob("*.md"):
            shutil.copy(f, data_dir / f.name)
        logging.info("Copied seed knowledge base to data/")
    init_db()

    # Auto-index các file .md chưa có embeddings
    from app.services.embeddings import EMBED_ENABLED, index_document, get_indexed_sources
    if EMBED_ENABLED:
        indexed = get_indexed_sources()
        md_files = list(data_dir.glob("*.md"))
        to_index = [f for f in md_files if f.stem not in indexed]
        if to_index:
            logging.info("Auto-indexing %d file(s) chưa có embeddings...", len(to_index))
            for f in to_index:
                try:
                    content = f.read_text(encoding="utf-8")
                    await index_document(f.stem, f.stem.replace("_", " ").title(), content)
                except Exception as e:
                    logging.error("Index lỗi %s: %s", f.name, e)
            logging.info("Auto-index hoàn tất.")


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
