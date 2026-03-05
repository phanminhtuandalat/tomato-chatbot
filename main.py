"""
Entry point — khởi tạo app và mount routers.
"""

import logging
import os

import uvicorn
from fastapi import FastAPI
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
    from pathlib import Path
    Path("data").mkdir(exist_ok=True)
    init_db()


@app.get("/")
async def index():
    return FileResponse("static/index.html")


@app.get("/health")
async def health():
    from app.services.rag import rag
    return {"status": "ok", "chunks": rag.chunk_count}


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
