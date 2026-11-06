"""組員 4：知識庫統一資料格式（schema）與共用小工具。

所有組員的成果最後都會被整理成這裡定義的格式，寫入 output/index.jsonl。
其他程式（validator、statistics_report、kb_search）只依賴這個檔案的定義，
所以欄位有變動時只要改這裡。

狀態分成三層，避免「網址下載成功，但正文清理失敗卻被算成成功」：
  crawl_status       取得階段（老師要求的欄位）：success / failed / unavailable / pending
  content_status     內容階段：ok / low_quality / fallback / missing / not_applicable
  processing_status  整體結果（統計用）：complete / partial / failed / unavailable / pending
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit

SCHEMA_VERSION = "1.0"

# 老師規定的欄位（validator 會檢查每筆都有）
REQUIRED_FIELDS = [
    "id", "type", "title", "source_url", "source_name", "content",
    "images", "links", "timestamps", "crawl_status", "crawled_at",
]

TYPES = {"web", "video"}

CRAWL_STATUS = {
    "success": "成功",
    "failed": "失敗",
    "unavailable": "無法存取",
    "pending": "未處理",
}
CONTENT_STATUS = {
    "ok": "內容可用",
    "low_quality": "內容品質不足（保留但不納入分析）",
    "fallback": "暫用原始 HTML 粗略擷取（待組員 2 清理）",
    "missing": "尚無清理後內容",
    "not_applicable": "不適用",
}
PROCESSING_STATUS = {
    "complete": "完整完成",
    "partial": "部分完成",
    "failed": "失敗",
    "unavailable": "無法存取",
    "pending": "未處理",
}

# 查證結論（report/source_verification.csv 的 verdict 欄）
VERDICTS = {"已證實", "資料不足", "有衝突"}


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def youtube_id(url: str) -> str:
    """從各種 YouTube 網址取出 11 碼影片 ID；不是 YouTube 就回傳空字串。"""
    try:
        p = urlsplit(url or "")
    except ValueError:
        return ""
    host = (p.hostname or "").lower()
    if host in {"youtu.be", "www.youtu.be"}:
        return p.path.strip("/").split("/")[0]
    if host.endswith("youtube.com"):
        if p.path == "/watch":
            return parse_qs(p.query).get("v", [""])[0]
        parts = p.path.strip("/").split("/")
        if len(parts) > 1 and parts[0] in {"shorts", "embed", "live"}:
            return parts[1]
    return ""


def seconds_to_hms(sec) -> str:
    try:
        s = max(0, int(float(sec)))
    except (TypeError, ValueError):
        return ""
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def compact(text: str) -> str:
    """去掉所有空白，用來比對引用原句（字幕常被拆成很多行）。"""
    return re.sub(r"\s+", "", str(text or ""))


def empty_record(record_id: str) -> dict:
    """一筆空白紀錄。轉接器（kb_sources.py）會把各組員的資料往上填。"""
    return {
        # ---- 老師規定的欄位 ----
        "id": record_id,
        "type": "web",
        "title": "",
        "source_url": "",
        "source_name": "",
        "content": "",
        "images": [],
        "links": [],
        "timestamps": [],
        "crawl_status": "pending",
        "crawled_at": "",
        # ---- 狀態細節 ----
        "crawl_status_label": CRAWL_STATUS["pending"],
        "crawl_reason": "尚無爬取紀錄",
        "content_status": "missing",
        "content_source": "",
        "content_usable": False,
        "processing_status": "pending",
        "pipeline": {},
        # ---- 來源資訊（來自 urls.csv）----
        "origin": "",
        "publisher": "",
        "topic_hint": "",
        "geo_scope": "",
        "source_role": "",
        "review_status": "",
        "enabled": True,
        "parent_id": None,
        "final_url": "",
        "http_status": None,
        "author": "",
        "published_at": "",
        # ---- 組員 4 分析結果（knowledge_builder 填寫）----
        "keywords": [],
        "topics": {},
        "duplicate_of": None,
        "similar_to": [],
        "quality_flags": [],
        "id_aliases": [],
        "metadata": {},
        "schema_version": SCHEMA_VERSION,
        "built_at": "",
    }


def finalize_status(rec: dict) -> None:
    """依取得狀態與內容狀態推出整體狀態（統計時用這個，不用 crawl_status）。"""
    crawl, content = rec["crawl_status"], rec["content_status"]
    rec["crawl_status_label"] = CRAWL_STATUS.get(crawl, crawl)
    if crawl in ("failed", "unavailable", "pending"):
        rec["processing_status"] = crawl
    elif content == "ok":
        rec["processing_status"] = "complete"
    else:
        rec["processing_status"] = "partial"
    rec["content_usable"] = content == "ok"
