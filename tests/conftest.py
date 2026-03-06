"""
Setup môi trường test — chạy trước tất cả tests.
"""

import os
import tempfile
from pathlib import Path
import pytest

# 1. Env vars phải đặt TRƯỚC khi import bất kỳ module app nào
os.environ.setdefault("OPENROUTER_API_KEY", "test-key-not-real")
os.environ.setdefault("ADMIN_PASSWORD",     "testpass")
os.environ.setdefault("ADMIN_USER",         "admin")

# 2. Dùng DB tạm thời để test không ảnh hưởng dữ liệu thật
_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp_db.close()

import app.database as _db_module
_db_module.DB_PATH = Path(_tmp_db.name)

# 3. Khởi tạo schema DB một lần cho toàn session
from app.database import init_db
init_db()


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient
    from main import app
    # Dùng context manager để trigger startup event
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
