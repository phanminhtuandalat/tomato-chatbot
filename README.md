# Chatbot Tư Vấn Cà Chua

Chatbot AI hỗ trợ nông dân trồng cà chua tại Việt Nam — tư vấn kỹ thuật, nhận dạng sâu bệnh qua ảnh, gắn với lịch mùa vụ.

**Demo:** https://web-production-b42bb.up.railway.app

---

## Cài đặt nhanh

### Cách 1 — Setup wizard (khuyên dùng)

```bash
git clone https://github.com/phanminhtuandalat/tomato-chatbot.git
cd tomato-chatbot
python setup.py
python main.py
```

Mở trình duyệt: **http://localhost:8000**

---

### Cách 2 — Docker

```bash
git clone https://github.com/phanminhtuandalat/tomato-chatbot.git
cd tomato-chatbot
cp .env.example .env
# Điền OPENROUTER_API_KEY và ADMIN_PASSWORD vào .env
docker-compose up -d
```

Mở trình duyệt: **http://localhost:8000**

---

### Cách 3 — Thủ công

```bash
git clone https://github.com/phanminhtuandalat/tomato-chatbot.git
cd tomato-chatbot
pip install -r requirements.txt
cp .env.example .env
# Điền .env
python main.py
```

---

## Biến môi trường

| Biến | Bắt buộc | Mô tả |
|---|---|---|
| `OPENROUTER_API_KEY` | ✅ | Key từ openrouter.ai |
| `ADMIN_PASSWORD` | ✅ | Mật khẩu trang /admin |
| `OPENROUTER_MODEL` | | Mặc định: `anthropic/claude-sonnet-4-5` |
| `ADMIN_USER` | | Mặc định: `admin` |
| `ZALO_OA_ACCESS_TOKEN` | | Chỉ cần khi kết nối Zalo |
| `ZALO_APP_SECRET` | | Chỉ cần khi kết nối Zalo |
| `PORT` | | Mặc định: `8000` |

---

## Deploy lên Railway (1 phút)

1. Fork repo này về GitHub của bạn
2. Vào **railway.app** → New Project → Deploy from GitHub
3. Thêm Variables: `OPENROUTER_API_KEY`, `ADMIN_PASSWORD`
4. Xong — Railway tự build và cấp URL HTTPS

---

## Tính năng

- **Chat tiếng Việt** — hỏi về kỹ thuật trồng, sâu bệnh, phân bón, thu hoạch
- **Gửi ảnh** — chụp lá/quả bị bệnh, bot nhận dạng và tư vấn
- **Nhận diện giọng nói** — bấm mic, nói tiếng Việt, bot tự nghe
- **Lịch mùa vụ** — tư vấn đúng theo tháng hiện tại
- **Lịch sử hội thoại** — bot nhớ ngữ cảnh cuộc trò chuyện
- **Đánh giá 👍 👎** — nông dân phản hồi chất lượng câu trả lời

## Trang Admin (/admin)

- Upload tài liệu: PDF, DOCX, TXT, URL web, ảnh sách/infographic
- Xem và xoá tài liệu trong knowledge base
- Xem thống kê đánh giá từ nông dân

---

## Chạy tests

```bash
pytest tests/
```

---

## Cấu trúc project

```
tomato-chatbot/
├── app/
│   ├── config.py         # env vars, validation
│   ├── database.py       # SQLite
│   ├── routers/
│   │   ├── chat.py       # /api/chat, /api/feedback
│   │   ├── admin.py      # /admin/*
│   │   └── zalo.py       # /webhook/zalo
│   └── services/
│       ├── llm.py        # OpenRouter API
│       └── rag.py        # RAG search, thread-safe
├── data/                 # knowledge base (.md files)
├── static/               # web UI
├── tests/                # pytest
├── main.py               # entry point
├── setup.py              # setup wizard
├── ingest.py             # CLI thêm tài liệu
└── docker-compose.yml
```
