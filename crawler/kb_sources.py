"""組員 4：來源轉接器（adapter）——把各組員的成果讀進統一格式。

設計重點：可擴充
  * 每一種資料來源寫成一個 SourceAdapter 子類別，加上 @register 就會自動被 builder 使用。
  * 以後來源增加：
      - 新網址：用組員 1 的 url_cli 加進 urls.csv，重新 build 就會出現，不用改程式。
      - 新「類型」的來源（RSS、PDF、開放資料 API…）：在這裡（或新檔案）寫一個新的 Adapter。
  * 轉接器之間用「網址」與「YouTube 影片 ID」對應到 urls.csv 的正式 ID，
    所以就算某個模組用了別的 ID（例如 video_2hbu5n9VLZY），也能接回 page_026。

執行順序由 order 決定（數字小的先執行，後面的可以覆蓋前面的欄位）：
  10 RegistryAdapter       urls.csv：建立每個來源的基本紀錄（31 筆老師網址＋額外來源）
  20 CrawlReportAdapter    組員 1 output/crawl_report.csv、output/links/{id}.json
  30 ArticleAdapter        組員 2 output/articles/{id}.json 或 {id}.md
  35 RawHtmlFallbackAdapter（選用）組員 2 尚未完成時，從 raw_html 粗略取文字
  40 VideoAdapter          組員 3 output/videos/{id}.json
  50 VideoQualityAdapter   組員 3 output/video_quality/{id}.json（字幕可不可用）
"""
from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from .kb_schema import compact, empty_record, seconds_to_hms, youtube_id
from .url_manager import canonical, read_rows

# 連結裡出現這些字，視為和觀音主題相關（與組員 1 main.py 的 KEYWORDS 一致並擴充）
RELEVANT_LINK_WORDS = ("觀音", "guanyin", "kuangin", "草漯", "白沙岬", "藻礁", "大潭", "崙坪",
                       "蓮花", "甘泉", "沙丘", "hakka", "lotus", "caota", "baishajia", "datan",
                       "ganquan", "lunping")


@dataclass
class BuildContext:
    """轉接器共用的設定與 ID 對照表。"""
    root: Path
    urls_file: Path
    output_dir: Path
    options: dict = field(default_factory=dict)
    url_to_id: dict = field(default_factory=dict)   # canonical(url) -> id
    video_to_id: dict = field(default_factory=dict)  # YouTube 影片 ID -> id
    log: list = field(default_factory=list)          # 建置過程的提醒，最後寫進報告

    def note(self, msg: str) -> None:
        self.log.append(msg)

    def resolve(self, record_id: str = "", url: str = "", records: dict | None = None) -> str:
        """找出正式 ID：先看 ID 本身，再用影片 ID、網址對應。"""
        if records is not None and record_id in records:
            return record_id
        vid = youtube_id(url)
        if vid and vid in self.video_to_id:
            return self.video_to_id[vid]
        if url:
            try:
                key = canonical(url)
            except ValueError:
                key = ""
            if key in self.url_to_id:
                return self.url_to_id[key]
        if record_id.startswith("video_") and record_id[6:] in self.video_to_id:
            return self.video_to_id[record_id[6:]]
        return ""


ADAPTERS: list[type["SourceAdapter"]] = []


def register(cls):
    """裝飾器：把轉接器加入清單。"""
    ADAPTERS.append(cls)
    ADAPTERS.sort(key=lambda c: c.order)
    return cls


class SourceAdapter:
    name = "base"
    order = 100
    optional = False   # True：要在 options 打開才會執行

    def enabled(self, ctx: BuildContext) -> bool:
        return not self.optional or bool(ctx.options.get(self.name))

    def apply(self, ctx: BuildContext, records: dict[str, dict]) -> None:
        raise NotImplementedError


# ---------------------------------------------------------------- 小工具
def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return default


def read_csv(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def host_of(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


def normalize_links(urls: list, page_url: str, limit: int = 300) -> list[dict]:
    host = host_of(page_url).removeprefix("www.")
    out, seen = [], set()
    for item in urls:
        url = item.get("url") if isinstance(item, dict) else str(item)
        text = item.get("text", "") if isinstance(item, dict) else ""
        if not url or url in seen:
            continue
        seen.add(url)
        low = url.lower()
        out.append({
            "url": url,
            "text": text,
            "internal": host_of(url).removeprefix("www.") == host,
            "relevant": any(w in low or w in text for w in RELEVANT_LINK_WORDS),
        })
    out.sort(key=lambda x: (not x["relevant"], not x["internal"]))
    return out[:limit]


# ---------------------------------------------------------------- 10 網址清單
@register
class RegistryAdapter(SourceAdapter):
    """urls.csv（組員 1 維護）：每一列都會有一筆紀錄，即使還沒爬也會出現（狀態 pending）。"""
    name, order = "registry", 10

    def apply(self, ctx, records):
        if not ctx.urls_file.is_file():
            ctx.note(f"找不到網址清單 {ctx.urls_file}")
            return
        for row in read_rows(ctx.urls_file):
            rid = row["id"]
            rec = records.setdefault(rid, empty_record(rid))
            url = row["url"]
            rec.update({
                "type": "video" if row.get("type") == "video" or youtube_id(url) else "web",
                "source_url": url,
                "title": row.get("title_hint", "") or rec["title"],
                "source_name": row.get("publisher", "") or host_of(url),
                "origin": row.get("origin", ""),
                "publisher": row.get("publisher", ""),
                "topic_hint": row.get("topic", ""),
                "geo_scope": row.get("geo_scope", ""),
                "source_role": row.get("source_role", "") or "content",
                "review_status": row.get("review_status", ""),
                "enabled": str(row.get("enabled", "true")).lower() in ("true", "1", "yes"),
            })
            rec["pipeline"]["registry"] = {"file": ctx.urls_file.name, "notes": row.get("notes", "")}
            if rec["geo_scope"] == "cross_area":
                rec["quality_flags"].append("cross_area：跨區頁面，只能採用觀音相關段落")
            if rec["source_role"] == "discovery":
                rec["quality_flags"].append("discovery：目錄頁，只用來找連結，不當作知識文章")
            try:
                ctx.url_to_id[canonical(url)] = rid
            except ValueError:
                pass
            vid = youtube_id(url)
            if vid:
                ctx.video_to_id[vid] = rid


# ---------------------------------------------------------------- 20 爬取紀錄
def read_site_snapshot(path: Path) -> list[dict]:
    """讀 site/index.html 中 `const data=[...]` 的資料（組員 1 build_site 產生），
    只取有爬取紀錄的列，欄位名稱與 crawl_report.csv 相同。"""
    if not path.is_file():
        return []
    html = path.read_text(encoding="utf-8", errors="replace")
    start = html.find("const data=")
    if start < 0:
        return []
    try:
        data, _ = json.JSONDecoder().raw_decode(html[start + len("const data="):].lstrip())
    except ValueError:
        return []
    rows = []
    for r in data if isinstance(data, list) else []:
        if isinstance(r, dict) and r.get("id") and r.get("crawl_status"):
            rows.append({"id": r["id"], "source_url": r.get("url", ""), "crawl_status": r["crawl_status"],
                         "reason": r.get("reason", ""), "http_status": r.get("http_status", ""),
                         "crawled_at": r.get("crawled_at", ""), "title": "", "final_url": ""})
    return rows


FETCH_MAP = {"success": "success", "failed": "failed", "unavailable": "unavailable",
             "pending_video": "pending", "video_pending": "pending"}


@register
class CrawlReportAdapter(SourceAdapter):
    """組員 1 的 crawl_report.csv（取得階段）與 links/{id}.json（超連結）。"""
    name, order = "crawl_report", 20

    def apply(self, ctx, records):
        path = ctx.output_dir / "crawl_report.csv"
        rows = read_csv(path)
        source_file = "crawl_report.csv"
        if not rows:
            # crawl_report.csv 被 .gitignore 排除、沒上 GitHub 時，
            # 改讀組員 1 build_site 嵌在 site/index.html 裡的同一份爬取紀錄（快照）
            rows = read_site_snapshot(ctx.root / "site" / "index.html")
            source_file = "site/index.html（爬取紀錄快照）"
            if rows:
                ctx.note(f"找不到 output/crawl_report.csv，改用 site/index.html 內嵌的爬取紀錄（{len(rows)} 筆，"
                         "為建站當時的快照；沒有 raw_html，網頁內容仍需組員 2 產生）")
        if not rows:
            ctx.note("尚無 output/crawl_report.csv 或 site/index.html 爬取紀錄，網頁將維持「未處理」")
            return
        latest: dict[str, dict] = {}
        for r in rows:  # 同一 ID 可能有多筆，取最新
            rid = r.get("id", "")
            if rid and (rid not in latest or r.get("crawled_at", "") >= latest[rid].get("crawled_at", "")):
                latest[rid] = r
        for raw_id, r in latest.items():
            if raw_id.startswith("manual_"):
                ctx.note(f"略過臨時測試 ID {raw_id}（不代表正式來源）")
                continue
            rid = ctx.resolve(raw_id, r.get("source_url", ""), records)
            if not rid:
                # 組員 1 --explore 延伸出來的頁面，例如 extra_001_extra_01
                m = re.match(r"(.+)_extra_\d+$", raw_id)
                if not m:
                    ctx.note(f"crawl_report 中的 {raw_id} 不在 urls.csv，略過")
                    continue
                rid = raw_id
                rec = records.setdefault(rid, empty_record(rid))
                rec.update({"origin": "discovered", "parent_id": m.group(1), "source_role": "content",
                            "source_url": r.get("source_url", ""), "geo_scope": "pending_review"})
                rec["quality_flags"].append("discovered：延伸探索取得，未經人工審核")
            rec = records[rid]
            if rid != raw_id and raw_id not in rec["id_aliases"]:
                rec["id_aliases"].append(raw_id)
            status = FETCH_MAP.get((r.get("crawl_status") or "").strip(), "failed")
            if rec["type"] == "video" and status == "pending":
                continue  # 影片交給 VideoAdapter 判斷
            rec["crawl_status"] = status
            rec["crawl_reason"] = r.get("reason", "") or ("" if status == "success" else "未記錄原因")
            rec["crawled_at"] = r.get("crawled_at", "") or rec["crawled_at"]
            rec["final_url"] = r.get("final_url", "")
            rec["http_status"] = int(r["http_status"]) if str(r.get("http_status", "")).isdigit() else None
            if r.get("title") and (not rec["title"] or rec["origin"] == "teacher"):
                rec["title"] = r["title"].strip()
            if r.get("source_name") and not rec["publisher"]:
                rec["source_name"] = r["source_name"]
            rec["pipeline"]["fetch"] = {"file": source_file, "status": r.get("crawl_status", ""),
                                        "http_status": r.get("http_status", ""), "reason": r.get("reason", ""),
                                        "sha256": r.get("sha256", "")}
            if status == "success" and rec["type"] == "web":
                rec["content_status"] = "missing"
                rec["crawl_reason"] = ""
            links = read_json(ctx.output_dir / "links" / f"{raw_id}.json", [])
            if links:
                rec["links"] = normalize_links(links, rec["final_url"] or rec["source_url"])
                rec["metadata"]["links_total"] = len(links)


# ---------------------------------------------------------------- 30 組員 2 文章
def parse_markdown_article(text: str) -> dict:
    """讀組員 2 的 Markdown：可有 --- front matter ---；圖片用 ![說明](路徑)。"""
    meta, body = {}, text
    if text.startswith("---"):
        parts = text.split("\n---", 2)
        if len(parts) >= 2:
            for line in parts[0].splitlines()[1:]:
                if ":" in line:
                    k, v = line.split(":", 1)
                    meta[k.strip()] = v.strip().strip('"')
            body = parts[1].lstrip("-\n") if len(parts) == 2 else parts[2]
    images = []
    for m in re.finditer(r"!\[([^\]]*)\]\(([^)\s]+)\)(?:\s*\n\s*\*?[^\n]*?來源[:：]\s*<?(https?://[^\s>*]+))?", body):
        images.append({"file": m.group(2).replace("../", ""), "caption": m.group(1), "source_url": m.group(3) or ""})
    plain = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", body)
    plain = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", plain)
    plain = re.sub(r"^#{1,6}\s*", "", plain, flags=re.M)
    plain = re.sub(r"[*_`>|]", "", plain)
    plain = "\n".join(l.strip() for l in plain.splitlines() if l.strip() and not set(l.strip()) <= set("-: "))
    return {**meta, "content": plain, "images": images}


@register
class ArticleAdapter(SourceAdapter):
    """組員 2 的清理結果。支援兩種格式（擇一即可，JSON 優先）：

    output/articles/{id}.json：
      {"id", "title", "content", "author", "published_at",
       "images": [{"file": "images/page_001_image_01.jpg", "caption": "...", "source_url": "https://..."}],
       "links": [...]}
    output/articles/{id}.md：可含 front matter（title/author/published_at），正文與 ![說明](圖片路徑)
    """
    name, order = "articles", 30

    def apply(self, ctx, records):
        folder = ctx.output_dir / "articles"
        if not folder.is_dir():
            ctx.note("尚無 output/articles/（組員 2 的正文清理成果），網頁內容先標為「尚無清理後內容」")
            return
        min_chars = int(ctx.options.get("min_content_chars", 80))
        files = sorted(folder.glob("*.json")) + sorted(p for p in folder.glob("*.md")
                                                       if not (folder / f"{p.stem}.json").exists())
        for path in files:
            data = read_json(path, None) if path.suffix == ".json" else \
                parse_markdown_article(path.read_text(encoding="utf-8-sig"))
            if not isinstance(data, dict):
                ctx.note(f"無法讀取 {path.name}")
                continue
            raw_id = str(data.get("id") or path.stem)
            rid = ctx.resolve(raw_id, data.get("source_url", ""), records)
            if not rid:
                ctx.note(f"文章 {path.name} 對不到 urls.csv 中的來源，略過")
                continue
            rec = records[rid]
            content = str(data.get("content", "")).strip()
            rec["content"] = content
            rec["content_source"] = f"articles/{path.name}"
            rec["content_status"] = "ok" if len(compact(content)) >= min_chars else "low_quality"
            if rec["content_status"] == "low_quality":
                rec["quality_flags"].append(f"正文少於 {min_chars} 字")
            for k in ("title", "author", "published_at"):
                if data.get(k):
                    rec[k] = str(data[k]).strip()
            imgs = []
            for img in data.get("images") or []:
                if isinstance(img, str):
                    img = {"file": img}
                f = str(img.get("file") or img.get("path") or "").replace("\\", "/").lstrip("./")
                if f and not f.startswith("images/") and "/" not in f:
                    f = "images/" + f
                imgs.append({**img, "file": f, "caption": img.get("caption") or img.get("alt") or "",
                             "source_url": img.get("source_url") or img.get("src") or "",
                             "article_id": rid, "kind": "article_image"})
            rec["images"] = imgs
            if data.get("links"):
                rec["links"] = normalize_links(data["links"], rec["final_url"] or rec["source_url"])
            if rec["crawl_status"] == "pending":  # 有文章表示已取得網頁
                rec["crawl_status"], rec["crawl_reason"] = "success", ""
            rec["pipeline"]["content"] = {"file": rec["content_source"], "status": rec["content_status"],
                                          "chars": len(compact(content)), "images": len(imgs)}


# ---------------------------------------------------------------- 35 選用：raw_html 粗略擷取
@register
class RawHtmlFallbackAdapter(SourceAdapter):
    """組員 2 尚未完成時的暫代方案（需加 --fallback-raw-html）。
    只做最基本的去標籤，content_status 標為 fallback，不會被當成「完整完成」。"""
    name, order, optional = "fallback_raw_html", 35, True

    def apply(self, ctx, records):
        from bs4 import BeautifulSoup
        folder = ctx.output_dir / "raw_html"
        for rid, rec in records.items():
            if rec["type"] != "web" or rec["content_status"] in ("ok", "low_quality"):
                continue
            path = folder / f"{rid}.html"
            if not path.is_file():
                continue
            soup = BeautifulSoup(path.read_text(encoding="utf-8", errors="replace"), "html.parser")
            for tag in soup(["script", "style", "noscript", "nav", "header", "footer", "aside", "form", "iframe"]):
                tag.decompose()
            main = soup.find("article") or soup.find("main") or soup.body or soup
            lines = [l.strip() for l in main.get_text("\n").splitlines()]
            text = "\n".join(l for l in lines if len(l) >= 8)
            if compact(text):
                rec["content"] = text
                rec["content_source"] = f"raw_html/{rid}.html（粗略擷取）"
                rec["content_status"] = "fallback"
                rec["quality_flags"].append("fallback：正文未經組員 2 清理，可能含選單雜訊")
                rec["pipeline"]["content"] = {"file": rec["content_source"], "status": "fallback"}


# ---------------------------------------------------------------- 40 組員 3 影片
UNAVAILABLE_HINTS = ("private", "unavailable", "removed", "sign in", "登入", "私人", "不存在", "age")


@register
class VideoAdapter(SourceAdapter):
    """組員 3 的 output/videos/{id}.json。保留組員 3 原本的欄位（他的頁面會讀），再補上統一欄位。"""
    name, order = "videos", 40

    def apply(self, ctx, records):
        folder = ctx.output_dir / "videos"
        if not folder.is_dir():
            ctx.note("尚無 output/videos/（組員 3 的影片成果）")
            return
        for path in sorted(folder.glob("*.json")):
            data = read_json(path, None)
            if not isinstance(data, dict) or data.get("type") != "video":
                continue
            raw_id = str(data.get("id") or path.stem)
            url = data.get("source_url", "")
            rid = ctx.resolve(raw_id, url, records)
            if not rid:
                ctx.note(f"影片 {path.name} 對不到 urls.csv 中的來源，略過")
                continue
            rec = records[rid]
            if rid != raw_id:
                if raw_id not in rec["id_aliases"]:
                    rec["id_aliases"].append(raw_id)
                ctx.note(f"影片模組使用 ID「{raw_id}」，已依影片網址對應回正式 ID {rid}")
            rec["type"] = "video"
            raw_status = str(data.get("crawl_status", ""))
            low = raw_status.lower()
            if low.startswith("success"):
                rec["crawl_status"], rec["crawl_reason"] = "success", ""
            elif any(h in low for h in UNAVAILABLE_HINTS):
                rec["crawl_status"], rec["crawl_reason"] = "unavailable", raw_status
            else:
                rec["crawl_status"], rec["crawl_reason"] = "failed", raw_status or "影片處理失敗"
            rec["title"] = data.get("title") or rec["title"]
            rec["source_name"] = data.get("source_name") or rec["source_name"]
            rec["crawled_at"] = data.get("crawled_at") or rec["crawled_at"]
            meta = data.get("metadata") or {}
            rec["metadata"].update(meta)
            if meta.get("upload_date") and len(str(meta["upload_date"])) == 8:
                d = str(meta["upload_date"])
                rec["published_at"] = f"{d[:4]}-{d[4:6]}-{d[6:]}"
            segs = data.get("timestamps") or []
            rec["timestamps"] = segs  # 保留組員 3 格式：start/end/start_seconds/end_seconds/text
            vid = meta.get("video_id") or youtube_id(url)
            frames = []
            for img in data.get("images") or []:
                fname = img.get("filename") or Path(str(img.get("path", ""))).name
                sec = img.get("seconds")
                frames.append({**img,
                               "file": f"images/{fname}" if fname else "",
                               "caption": img.get("description", ""),
                               "time": seconds_to_hms(sec),
                               "source_url": f"https://www.youtube.com/watch?v={vid}&t={int(float(sec or 0))}s" if vid else url,
                               "article_id": rid, "kind": "video_frame"})
            rec["images"] = frames
            content = str(data.get("content", "")).strip()
            has_text = bool(segs) and bool(compact(content)) and "無可用字幕" not in content
            rec["content"] = content if has_text else ""
            rec["content_source"] = f"videos/{path.name}"
            rec["content_status"] = "ok" if has_text else "missing"
            if not has_text and rec["crawl_status"] == "success":
                rec["quality_flags"].append("影片沒有可用字幕：只有影片資訊與代表畫面")
            m = re.search(r"\(([^()]+)", raw_status)
            rec["pipeline"]["video"] = {"file": f"videos/{path.name}", "raw_status": raw_status,
                                        "subtitle_source": m.group(1).strip() if m else "",
                                        "segments": len(segs), "frames": len(frames)}
            rec["links"] = normalize_links(data.get("links") or [url], url)


# ---------------------------------------------------------------- 50 組員 3 品質判定
EXCLUDE_STATES = ("visual_only", "rejected", "unusable", "noise", "failed")


@register
class VideoQualityAdapter(SourceAdapter):
    """組員 3 的 output/video_quality/{id}.json：usable_for_knowledge=false 的字幕不納入分類與關鍵字。"""
    name, order = "video_quality", 50

    def apply(self, ctx, records):
        folder = ctx.output_dir / "video_quality"
        if not folder.is_dir():
            return
        for path in sorted(folder.glob("*.json")):
            if path.stem == "summary":
                continue
            q = read_json(path, None)
            if not isinstance(q, dict):
                continue
            rid = ctx.resolve(str(q.get("id") or path.stem), q.get("source_url", ""), records)
            if not rid or records[rid]["type"] != "video":
                continue
            rec = records[rid]
            state, reason = q.get("quality_state", ""), q.get("quality_reason", "")
            rec["pipeline"]["quality"] = {"file": f"video_quality/{path.name}", "state": state,
                                          "reason": reason, "usable_for_knowledge": q.get("usable_for_knowledge"),
                                          "metrics": q.get("metrics", {})}
            # visual_only / rejected 等：組員 3 明確判定字幕不可用 → 不納入分類與關鍵字
            # needs_review：字幕已取得但尚未人工審核 → 仍可分析，但加上提醒
            exclude = set(ctx.options.get("video_exclude_states", EXCLUDE_STATES))
            if rec["content_status"] == "ok" and state in exclude:
                rec["content_status"] = "low_quality"
                rec["quality_flags"].append(f"字幕品質：{state}（{reason}）")
            elif state and state != "approved":
                rec["quality_flags"].append(f"字幕待審核：{state}（{reason}）")
