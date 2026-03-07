# CLAUDE.md — Hướng dẫn cho Claude Code Agent

## Quy tắc bắt buộc — Memory Update

**SAU MỖI TASK** thay đổi code, trước khi kết thúc conversation, tự động:

1. Xác định file memory nào bị ảnh hưởng:
   - Thêm/sửa API endpoint → cập nhật `memory/api_endpoints.md`
   - Thay đổi DB schema hoặc helper → cập nhật `memory/database.md`
   - Thêm/sửa tính năng → cập nhật `memory/features.md`
   - Thay đổi frontend (app.js, index.html) → cập nhật `memory/frontend.md`
   - Phát hiện pattern/pitfall mới → cập nhật `memory/patterns.md`
   - Thay đổi lớn ảnh hưởng tổng thể → cập nhật `memory/MEMORY.md`

2. Ghi vào đúng file memory tương ứng — KHÔNG tạo file mới trừ khi thực sự cần topic mới.

3. Chỉ ghi những gì **ổn định và đã verified** — không ghi thông tin tạm thời hay đang thử nghiệm.

Memory dir: `C:\Users\PHANMINHTUAN\.claude\projects\C--Users-PHANMINHTUAN-tomato-chatbot\memory\`

---

## Ngôn ngữ & Style
- Comments, docstrings, log messages, strings hiển thị cho user: **tiếng Việt**
- Tên biến/hàm: tiếng Anh (snake_case Python, camelCase JS)
- Không thêm emoji trừ khi user yêu cầu

## Khi thay đổi frontend (CSS/JS)
- Luôn update version string trong `static/index.html`:
  `?v=YYYYMMDD_X` (X là a, b, c... nếu cùng ngày)

## Khi thêm file .md vào KB (data/)
- Luôn gọi `rag.reload()` sau khi lưu
- Nếu EMBED_ENABLED: gọi thêm `await index_document(...)`

## Không làm
- Không commit code trừ khi user yêu cầu rõ ràng
- Không push lên remote trừ khi được yêu cầu
- Không xóa file trừ khi được yêu cầu
