# Chatbot Cà Chua — Zalo OA

Chatbot tư vấn trồng cà chua cho nông dân Việt Nam, tích hợp Zalo OA + Claude API.

## Cài đặt

```bash
cd tomato-chatbot
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # Linux/Mac

pip install -r requirements.txt
```

## Cấu hình

```bash
cp .env.example .env
# Mở .env và điền vào:
# ANTHROPIC_API_KEY=sk-ant-...
# ZALO_OA_ACCESS_TOKEN=...
# ZALO_APP_SECRET=...
```

## Chạy local

```bash
python main.py
# Server chạy tại http://localhost:8000
```

Để test webhook từ Zalo, cần expose ra internet bằng ngrok:

```bash
ngrok http 8000
# Copy URL https://xxx.ngrok.io/webhook/zalo vào Zalo Developer Console
```

## Deploy lên Railway

1. Tạo tài khoản tại railway.app
2. New Project → Deploy from GitHub repo
3. Thêm biến môi trường trong Settings → Variables
4. Railway tự động build và deploy

## Cấu trúc project

```
tomato-chatbot/
├── main.py              # FastAPI app + Zalo webhook
├── claude_client.py     # Gọi Claude API
├── knowledge_base.py    # RAG keyword search
├── zalo_client.py       # Gửi tin nhắn Zalo
├── data/
│   └── tomato_knowledge.md  # Kho kiến thức cà chua
├── requirements.txt
└── .env.example
```

## Mở rộng knowledge base

Thêm file `.md` vào thư mục `data/` — hệ thống tự động đọc khi khởi động.
