"""
Self-Evolution Engine — tự động phát hiện và lấp đầy knowledge gaps.

Vòng lặp:
  1. Phân tích flywheel → tìm gaps (từ/cụm từ hay hỏi nhưng KB chưa cover)
  2. Với mỗi gap đủ lớn (count >= GAP_MIN_COUNT): AI viết bài → lưu vào KB
  3. Ghi log lịch sử vào evolution_log
  4. Chạy tự động mỗi đêm lúc EVOLUTION_HOUR giờ

Chạy thủ công: POST /admin/run-evolution
"""

import asyncio
import logging
import re
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path

log = logging.getLogger(__name__)

# ── Config ──────────────────────────────────────────────────────────────────
GAP_MIN_COUNT     = 3   # số lần hỏi tối thiểu để trigger fill
GAP_MAX_PER_CYCLE = 5   # tối đa gaps fill mỗi chu kỳ (kiểm soát chi phí LLM)
EVOLUTION_HOUR    = 2   # giờ chạy tự động (2 AM)

DATA_DIR = Path(__file__).parent.parent.parent / "data"

_GAP_PROMPT_TEMPLATE = """Bạn là chuyên gia trồng cà chua Việt Nam. Viết một bài kiến thức ngắn (~400 từ) về chủ đề: "{topic}"

Cấu trúc bài:
# [Tiêu đề rõ ràng về {topic}]

## Tổng quan
[2-3 câu giới thiệu]

## Triệu chứng / Đặc điểm
[Mô tả cụ thể bà con nhận biết]

## Nguyên nhân
[Nguyên nhân chính]

## Cách xử lý
[Tên thuốc/biện pháp, liều lượng, thời điểm — cụ thể cho điều kiện Việt Nam]

## Phòng ngừa
[2-3 biện pháp phòng ngừa]

Yêu cầu: tiếng Việt, thực tế, có số liệu cụ thể (liều lượng, khoảng cách, thời gian). KHÔNG bịa đặt."""


# ── Core ─────────────────────────────────────────────────────────────────────

async def run_evolution_cycle() -> dict:
    """
    Chạy 1 chu kỳ tiến hóa đầy đủ.
    Trả về: {ts, gaps_found, gaps_filled, skipped, errors, details[]}
    """
    from app.database import get_flywheel_data, save_evolution_log

    ts = datetime.now().isoformat(timespec="seconds")
    log.info("[Evolution] Bắt đầu chu kỳ — %s", ts)

    # 1. Lấy gaps từ flywheel
    data     = get_flywheel_data()
    all_gaps = data.get("gaps", [])

    # 2. Filter: đủ count + chưa có file tương ứng trong data/
    candidates = [g for g in all_gaps if g["count"] >= GAP_MIN_COUNT]
    gaps_found = len(candidates)

    # Ưu tiên bigram (ngữ nghĩa rõ) và count cao nhất
    candidates.sort(key=lambda g: (g.get("is_bigram", False), g["count"]), reverse=True)
    targets = candidates[:GAP_MAX_PER_CYCLE]

    gaps_filled = 0
    skipped     = 0
    errors      = 0
    details     = []

    for gap in targets:
        topic = gap["word"]

        # Bỏ qua nếu đã có file KB tương ứng (tránh duplicate)
        if _topic_already_covered(topic):
            skipped += 1
            details.append({"topic": topic, "result": "skipped", "reason": "đã có trong KB"})
            continue

        try:
            filename, preview = await _fill_gap(topic)
            gaps_filled += 1
            details.append({"topic": topic, "result": "success", "file": filename, "preview": preview})
            save_evolution_log(ts, "gap_filled", topic, "success", filename)
            log.info("[Evolution] Đã fill gap '%s' → %s", topic, filename)

        except Exception as e:
            errors += 1
            details.append({"topic": topic, "result": "failed", "error": str(e)[:200]})
            save_evolution_log(ts, "gap_filled", topic, "failed", str(e)[:200])
            log.error("[Evolution] Lỗi fill gap '%s': %s", topic, e)

    # Ghi log tổng chu kỳ
    summary_msg = f"found={gaps_found} filled={gaps_filled} skipped={skipped} errors={errors}"
    save_evolution_log(ts, "cycle_complete", "", "success", summary_msg)

    result = {
        "ts":          ts,
        "gaps_found":  gaps_found,
        "gaps_filled": gaps_filled,
        "skipped":     skipped,
        "errors":      errors,
        "details":     details,
    }
    log.info("[Evolution] Hoàn tất: %s", summary_msg)
    return result


async def _fill_gap(topic: str) -> tuple[str, str]:
    """
    Viết bài về topic, lưu vào data/, reload RAG.
    Trả về (filename, preview_200_chars).
    """
    from app.services.llm import _call, OPENROUTER_MODEL
    from app.services import rag as rag_module
    from app.services.embeddings import index_document, EMBED_ENABLED

    prompt = _GAP_PROMPT_TEMPLATE.format(topic=topic)
    raw    = await _call(
        [{"role": "user", "content": prompt}],
        model=OPENROUTER_MODEL,
        max_tokens=700,
    )
    content = raw.strip()
    title   = f"Hướng dẫn: {topic}"

    out = _save_doc(title, content, f"evolution_{topic[:40]}")
    rag_module.rag.reload()
    if EMBED_ENABLED:
        await index_document(out.stem, title, out.read_text(encoding="utf-8"))

    return out.name, content[:200]


def _save_doc(title: str, content: str, source_hint: str) -> Path:
    """Lưu nội dung thành file .md trong data/."""
    name = unicodedata.normalize("NFD", title.lower())
    name = "".join(c for c in name if unicodedata.category(c) != "Mn")
    name = re.sub(r"[^\w\s-]", "", name)
    name = re.sub(r"[\s-]+", "_", name).strip("_")[:60] or "evolution"
    out  = DATA_DIR / f"{name}.md"
    out.write_text(
        f"# {title}\n\n> Nguồn: Tự động tạo từ Evolution Engine ({source_hint})\n\n{content}\n",
        encoding="utf-8",
    )
    return out


def _topic_already_covered(topic: str) -> bool:
    """
    Kiểm tra nhanh xem đã có file .md nào chứa topic này chưa.
    Dùng normalize để so sánh bỏ dấu.
    """
    norm_topic = unicodedata.normalize("NFD", topic.lower())
    norm_topic = "".join(c for c in norm_topic if unicodedata.category(c) != "Mn")

    for md_file in DATA_DIR.glob("*.md"):
        norm_name = unicodedata.normalize("NFD", md_file.stem.lower())
        norm_name = "".join(c for c in norm_name if unicodedata.category(c) != "Mn")
        if norm_topic.replace(" ", "_") in norm_name or norm_topic.replace(" ", "") in norm_name:
            return True
    return False


# ── Scheduler ────────────────────────────────────────────────────────────────

async def evolution_scheduler() -> None:
    """
    Background asyncio task — chạy vô hạn.
    Trigger run_evolution_cycle() mỗi ngày lúc EVOLUTION_HOUR giờ.
    """
    log.info("[Evolution] Scheduler khởi động — sẽ chạy mỗi ngày lúc %02d:00", EVOLUTION_HOUR)

    while True:
        try:
            now    = datetime.now()
            target = now.replace(hour=EVOLUTION_HOUR, minute=0, second=0, microsecond=0)
            if target <= now:
                target += timedelta(days=1)

            wait = (target - now).total_seconds()
            log.info("[Evolution] Lần chạy tiếp theo: %s (sau %.0fh%.0fm)",
                     target.strftime("%d/%m %H:%M"), wait // 3600, (wait % 3600) // 60)

            await asyncio.sleep(wait)
            await run_evolution_cycle()

        except asyncio.CancelledError:
            log.info("[Evolution] Scheduler dừng.")
            break
        except Exception as e:
            log.error("[Evolution] Lỗi không mong đợi: %s — thử lại sau 1 giờ", e)
            await asyncio.sleep(3600)
