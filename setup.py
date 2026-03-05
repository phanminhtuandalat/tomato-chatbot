"""
Wizard cài đặt tự động — chạy một lần duy nhất.
python setup.py
"""

import subprocess
import sys
from pathlib import Path

BANNER = """
╔══════════════════════════════════════════╗
║      CHATBOT CA CHUA — SETUP WIZARD     ║
╚══════════════════════════════════════════╝
"""

def ask(prompt: str, default: str = "") -> str:
    hint = f" [{default}]" if default else ""
    val = input(f"{prompt}{hint}: ").strip()
    return val or default

def ok(msg):  print(f"  \033[92m✓\033[0m {msg}")
def info(msg): print(f"  \033[94m→\033[0m {msg}")
def warn(msg): print(f"  \033[93m!\033[0m {msg}")
def err(msg):  print(f"  \033[91m✗\033[0m {msg}")

def main():
    print(BANNER)

    # ── Bước 1: Python version ──
    info("Kiểm tra Python...")
    if sys.version_info < (3, 10):
        err(f"Cần Python 3.10+, hiện tại: {sys.version}")
        sys.exit(1)
    ok(f"Python {sys.version.split()[0]}")

    # ── Bước 2: Cài dependencies ──
    info("Cài đặt thư viện...")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", "requirements.txt", "-q"],
        capture_output=True
    )
    if result.returncode != 0:
        err("Cài đặt thất bại. Chạy: pip install -r requirements.txt")
        sys.exit(1)
    ok("Đã cài xong thư viện")

    # ── Bước 3: Tạo .env ──
    env_path = Path(".env")
    if env_path.exists():
        overwrite = ask("\nĐã có file .env. Ghi đè?", "n").lower()
        if overwrite != "y":
            info("Giữ nguyên file .env hiện tại")
            finish()
            return

    print("\n📋 Điền thông tin cấu hình:\n")

    api_key = ask("OpenRouter API Key (lấy tại openrouter.ai)")
    while not api_key.startswith("sk-or"):
        warn("Key phải bắt đầu bằng 'sk-or'. Thử lại.")
        api_key = ask("OpenRouter API Key")

    model = ask("Model AI", "anthropic/claude-sonnet-4-5")
    admin_user = ask("Tên đăng nhập Admin", "admin")

    admin_pass = ask("Mật khẩu Admin (tối thiểu 8 ký tự)")
    while len(admin_pass) < 8:
        warn("Mật khẩu quá ngắn.")
        admin_pass = ask("Mật khẩu Admin")

    port = ask("Port server", "8000")

    env_content = f"""# OpenRouter API
OPENROUTER_API_KEY={api_key}
OPENROUTER_MODEL={model}

# Zalo OA (điền sau khi có OA)
ZALO_OA_ACCESS_TOKEN=
ZALO_APP_SECRET=

# Admin
ADMIN_USER={admin_user}
ADMIN_PASSWORD={admin_pass}

# Server
PORT={port}
"""
    env_path.write_text(env_content, encoding="utf-8")
    ok("Đã tạo file .env")

    finish()


def finish():
    print("\n" + "═" * 44)
    print("  Cài đặt hoàn tất! Chạy server:")
    print()
    print("    python main.py")
    print()
    print("  Sau đó mở: http://localhost:8000")
    print("  Trang Admin: http://localhost:8000/admin")
    print("═" * 44 + "\n")


if __name__ == "__main__":
    main()
