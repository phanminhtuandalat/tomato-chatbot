"""
Công cụ (tools) cho chatbot cà chua:
  - web_search: tìm kiếm thông tin mới nhất (giá, thị trường, dịch bệnh)
  - calculate: tính toán liều lượng phân bón, thuốc BVTV

Phát hiện tool bằng keyword matching — nhanh, không tốn thêm LLM call.
"""

import ast
import logging
import operator
import re

import httpx

from app.config import TAVILY_API_KEY

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Keyword detection — câu hỏi nào cần tìm kiếm internet
# ---------------------------------------------------------------------------

_SEARCH_PATTERNS = [
    r"\bgiá\b",                         # giá cà chua, giá phân bón
    r"bán .{0,20}ở đâu",
    r"mua .{0,20}ở đâu",
    r"\bthị trường\b",
    r"\bgiá cả\b",
    r"hôm nay|hôm qua|tuần này|tháng này",
    r"mới nhất|hiện nay|hiện tại|gần đây",
    r"tin tức|thông tin mới",
    r"dịch bệnh .{0,15}đang",
    r"đang xảy ra|đang bùng phát",
    r"thuốc .{0,20}còn bán|còn không",
    r"bao nhiêu tiền|chi phí|kinh phí",
    r"xuất khẩu|nhập khẩu",
    r"tìm kiếm|tra cứu",
]

_SEARCH_RE = re.compile("|".join(_SEARCH_PATTERNS), re.IGNORECASE | re.UNICODE)

_CALC_PATTERNS = [
    r"\btính\b",
    r"bao nhiêu (ml|lít|kg|g|gram|cc|m2|ha|hecta|gói|bình)",
    r"\d+\s*(ml|lít|kg|g|m2|ha|sào|công)\b.*\btính\b",
    r"pha.{0,20}bình \d+",
    r"liều lượng cho\b",
    r"cần (mấy|bao nhiêu).{0,30}(bình|lít|kg|gói|thuốc|phân)",
    r"diện tích\s*\d",
    r"(\d+)\s*[×x\*]\s*(\d+)",   # biểu thức nhân
]

_CALC_RE = re.compile("|".join(_CALC_PATTERNS), re.IGNORECASE | re.UNICODE)


def needs_search(question: str) -> bool:
    return bool(_SEARCH_RE.search(question))


def needs_calculate(question: str) -> bool:
    return bool(_CALC_RE.search(question))


# ---------------------------------------------------------------------------
# Web search — Tavily (primary) hoặc DuckDuckGo (fallback miễn phí)
# ---------------------------------------------------------------------------

async def web_search(query: str) -> str:
    """Tìm kiếm thông tin mới nhất. Trả về chuỗi kết quả để inject vào context."""
    if TAVILY_API_KEY:
        result = await _tavily_search(query)
        if result:
            return result
    return await _ddg_search(query)


async def _tavily_search(query: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            r = await client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": TAVILY_API_KEY,
                    "query": query,
                    "max_results": 5,
                    "search_depth": "basic",
                    "include_answer": True,
                    "include_domains": [],
                },
            )
            if r.status_code != 200:
                return ""
            data = r.json()

        parts: list[str] = []
        if data.get("answer"):
            parts.append(f"Tóm tắt: {data['answer']}")
        for res in data.get("results", [])[:5]:
            title   = res.get("title", "")
            content = res.get("content", "")[:400]
            url     = res.get("url", "")
            if content:
                parts.append(f"• {title}: {content}" + (f" ({url})" if url else ""))
        return "\n".join(parts) if parts else ""
    except Exception as e:
        log.warning("Tavily error: %s", e)
        return ""


async def _ddg_search(query: str) -> str:
    """Fallback: duckduckgo-search — kết quả tìm kiếm thật, miễn phí, không cần API key."""
    try:
        from ddgs import DDGS
        import asyncio

        def _sync_search() -> list[dict]:
            with DDGS() as ddgs:
                return list(ddgs.text(query, max_results=5, region="vn-vi"))

        results = await asyncio.get_event_loop().run_in_executor(None, _sync_search)
        if not results:
            return "Không tìm thấy thông tin mới trên internet."

        parts = [
            f"• {r['title']}: {r['body'][:350]}"
            for r in results if r.get("body")
        ]
        return "\n".join(parts) if parts else "Không tìm thấy thông tin mới trên internet."
    except ImportError:
        log.warning("ddgs chưa được cài. Chạy: pip install ddgs")
        return "Tính năng tìm kiếm chưa được cài đặt."
    except Exception as e:
        log.warning("DDG search error: %s", e)
        return "Không thể tìm kiếm lúc này."


# ---------------------------------------------------------------------------
# Calculator — eval an toàn (chỉ hỗ trợ phép tính số học)
# ---------------------------------------------------------------------------

_SAFE_OPS: dict = {
    ast.Add:  operator.add,
    ast.Sub:  operator.sub,
    ast.Mult: operator.mul,
    ast.Div:  operator.truediv,
    ast.Pow:  operator.pow,
    ast.Mod:  operator.mod,
    ast.USub: operator.neg,
}


def _safe_eval(node: ast.expr) -> float:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.BinOp):
        op = _SAFE_OPS.get(type(node.op))
        if op is None:
            raise ValueError("Phép tính không được hỗ trợ")
        left  = _safe_eval(node.left)
        right = _safe_eval(node.right)
        if isinstance(node.op, ast.Div) and right == 0:
            raise ValueError("Chia cho 0")
        return op(left, right)
    if isinstance(node, ast.UnaryOp):
        op = _SAFE_OPS.get(type(node.op))
        if op is None:
            raise ValueError("Không hỗ trợ")
        return op(_safe_eval(node.operand))
    raise ValueError(f"Không hỗ trợ: {type(node).__name__}")


def calculate(expression: str) -> str:
    """Tính toán an toàn, trả về chuỗi kết quả."""
    expr = expression.strip().replace(",", ".").replace("×", "*").replace("x", "*")
    try:
        tree = ast.parse(expr, mode="eval")
        result = _safe_eval(tree.body)
        display = int(result) if result == int(result) else round(result, 4)
        return f"{expr} = {display}"
    except Exception as e:
        return f"Không thể tính '{expr}': {e}"


# ---------------------------------------------------------------------------
# Extract expression từ câu hỏi tự nhiên để tính toán
# ---------------------------------------------------------------------------

def extract_expression(question: str) -> str | None:
    """Tìm biểu thức toán học trong câu hỏi tiếng Việt."""
    # Ví dụ: "2ml/lít × 16 lít bình" → "2*16"
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:ml/l[ií]t|ml\s*/\s*l)\s*[×x\*]?\s*(\d+(?:[.,]\d+)?)\s*l[ií]t", question, re.I)
    if m:
        return f"{m.group(1).replace(',','.')} * {m.group(2).replace(',','.')}"

    # Biểu thức đơn giản với số
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*([×x\*\/\+\-])\s*(\d+(?:[.,]\d+)?)", question)
    if m:
        op_map = {"×": "*", "x": "*"}
        op = op_map.get(m.group(2), m.group(2))
        return f"{m.group(1).replace(',','.')} {op} {m.group(3).replace(',','.')}"

    return None
