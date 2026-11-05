"""YouTube Video Extractor for Guanyin District Knowledge Base.

期中專案 - 組員 3：YouTube 影片字幕逐字稿與代表畫面擷取模組
對應任務 4A（字幕與 Whisper 轉錄）、4B（代表畫面擷取）與任務 5（資料整合與組員 4 規格）。

功能特點：
  1. 核心處理函式 process_video(entry, out_dir="output")：
     - 下載中繼資料與字幕（透過 yt-dlp）
     - 字幕優先順序：YouTube 官方/自動字幕 (.vtt) -> faster-whisper 音軌語音轉錄
     - 代表畫面擷取 (任務 4B)：智慧挑選 3~5 張代表畫面（優先匹配觀音區關鍵字或均勻影格，過濾純黑畫面）
     - 產出 output/videos/{id}.json、output/videos/{id}.md
     - 追加寫入 output/index.jsonl（組員 4 格式）
     - 回傳 crawler/main.py 規範字典（status, http_status, title, elapsed_ms 等）
  2. CLI 獨立執行入口：
     - python -m crawler.video_extractor
     - python -m crawler.video_extractor --url "https://youtu.be/..."
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

# Windows 終端編碼相容處理
if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# 觀音區景點與文化關鍵字 (用於代表畫面優先挑選)
GUANYIN_KEYWORDS = [
    "觀音", "白沙岬", "燈塔", "草漯", "沙丘", "甘泉寺", "向陽", "農場",
    "蓮花", "風車", "濱海", "大潭", "新屋", "文化", "藻礁", "寺廟", "景點",
    "guanyin", "kuangin", "hakka"
]

VIDEO_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{11}$")


def extract_video_id(url: str) -> Optional[str]:
    """從 YouTube 網址中擷取 11 字元的 video ID。"""
    if not url:
        return None
    url = html.unescape(url.strip())
    if not url.lower().startswith(("http://", "https://")):
        url = "https://" + url

    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    host = host.removeprefix("www.").removeprefix("m.").removeprefix("music.")
    video_id = None

    if host == "youtu.be":
        parts = parsed.path.strip("/").split("/")
        video_id = parts[0] if parts and parts[0] else None
    elif host in {"youtube.com", "youtube-nocookie.com"}:
        parts = parsed.path.strip("/").split("/")
        if parsed.path.rstrip("/") == "/watch":
            video_id = parse_qs(parsed.query).get("v", [None])[0]
        elif len(parts) >= 2 and parts[0].lower() in {"shorts", "embed", "live", "v"}:
            video_id = parts[1]

    if video_id and VIDEO_ID_PATTERN.fullmatch(video_id):
        return video_id
    return None


def format_seconds(seconds: float) -> str:
    """將秒數格式化為 HH:MM:SS 或 MM:SS。"""
    seconds = max(0.0, seconds)
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def parse_vtt_timestamp(ts_str: str) -> float:
    """將 VTT 時間戳記 (HH:MM:SS.mmm 或 MM:SS.mmm) 轉換為秒數。"""
    parts = ts_str.strip().split(":")
    if len(parts) == 3:
        h, m, s = parts
        return int(h) * 3600 + int(m) * 60 + float(s)
    elif len(parts) == 2:
        m, s = parts
        return int(m) * 60 + float(s)
    return 0.0


def parse_vtt(path: Path) -> List[Dict[str, Any]]:
    """解析 WebVTT 字幕檔為結構化的字幕段落。"""
    if not path.is_file():
        return []

    text = path.read_text(encoding="utf-8", errors="replace")
    blocks = re.split(r"\n\s*\n", text)
    rows: List[Dict[str, Any]] = []

    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        timing = next((line for line in lines if "-->" in line), None)
        if not timing:
            continue

        raw_start, raw_end = [x.strip().split()[0] for x in timing.split("-->", 1)]
        start_sec = round(parse_vtt_timestamp(raw_start), 3)
        end_sec = round(parse_vtt_timestamp(raw_end), 3)

        body_lines = lines[lines.index(timing) + 1:]
        body = " ".join(line for line in body_lines if not line.isdigit())
        body = re.sub(r"<[^>]+>", "", body).strip()

        if body:
            # 去除滾動式字幕中相鄰且重複的行
            if rows and rows[-1]["text"] == body and start_sec - rows[-1]["end_seconds"] <= 1.0:
                rows[-1]["end_seconds"] = end_sec
            else:
                rows.append({
                    "start": format_seconds(start_sec),
                    "end": format_seconds(end_sec),
                    "start_seconds": start_sec,
                    "end_seconds": end_sec,
                    "text": body,
                })

    return rows


def download_video_and_metadata(url: str, work_dir: Path) -> Dict[str, Any]:
    """使用 yt-dlp Python API 下載影片中繼資料、字幕與影片串流。"""
    work_dir.mkdir(parents=True, exist_ok=True)
    template = str(work_dir / "%(id)s.%(ext)s")

    # 嘗試取得 imageio-ffmpeg 執行檔路徑 (供 Windows 環境直接使用)
    ffmpeg_exe = None
    try:
        import imageio_ffmpeg
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass

    try:
        import yt_dlp
        ydl_opts = {
            "outtmpl": template,
            "format": "18/best[ext=mp4]/best",
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": ["zh-TW", "zh-Hant", "zh", "zh-Hans", "en"],
            "subtitlesformat": "vtt",
            "writeinfojson": True,
            "noplaylist": True,
            "ignoreerrors": True,
            "extractor_args": {
                "youtube": {
                    "player_client": ["android", "ios"]
                }
            },
            "quiet": False,
            "no_warnings": False,
        }
        if ffmpeg_exe:
            ydl_opts["ffmpeg_location"] = ffmpeg_exe

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        return {"status": "ok"}
    except Exception as exc:
        # 若已有下載檔案 (如 vtt 或 info.json 或影片)，視為成功抓取中繼資料
        if list(work_dir.glob("*.info.json")) or list(work_dir.glob("*.vtt")) or list(work_dir.glob("*.mp4")):
            return {"status": "ok"}
        raise RuntimeError(f"yt-dlp 下載失敗: {exc}")


def whisper_transcribe(audio_or_video: Path, model_name: str = "base") -> List[Dict[str, Any]]:
    """若無線上字幕，使用 faster-whisper（或 whisper）轉錄音軌。"""
    # 優先嘗試 faster-whisper
    try:
        from faster_whisper import WhisperModel
        model = WhisperModel(model_name, device="auto", compute_type="int8")
        segments, _ = model.transcribe(str(audio_or_video), vad_filter=True)
        results = []
        for s in segments:
            txt = s.text.strip()
            if txt:
                results.append({
                    "start": format_seconds(s.start),
                    "end": format_seconds(s.end),
                    "start_seconds": round(s.start, 3),
                    "end_seconds": round(s.end, 3),
                    "text": txt,
                })
        return results
    except ImportError:
        pass

    # 次選 standard openai-whisper
    try:
        import whisper
        model = whisper.load_model(model_name)
        res = model.transcribe(str(audio_or_video))
        results = []
        for s in res.get("segments", []):
            txt = s.get("text", "").strip()
            if txt:
                start_sec = round(float(s["start"]), 3)
                end_sec = round(float(s["end"]), 3)
                results.append({
                    "start": format_seconds(start_sec),
                    "end": format_seconds(end_sec),
                    "start_seconds": start_sec,
                    "end_seconds": end_sec,
                    "text": txt,
                })
        return results
    except ImportError:
        raise RuntimeError("未安裝語音辨識套件 (faster-whisper 或 openai-whisper)")


def extract_representative_frames(
    video_path: Path,
    output_dir: Path,
    item_id: str,
    timestamps: List[Dict[str, Any]],
    target_count: int = 4
) -> List[Dict[str, Any]]:
    """智慧擷取 3～5 張代表性畫面 (任務 4B)，避開純黑畫面。"""
    try:
        import cv2
    except ImportError:
        print("  [提示] 未安裝 opencv-python，跳過畫面截圖步驟")
        return []

    if not video_path.is_file():
        return []

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return []

    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    duration_seconds = total_frames / fps if fps > 0 else 0

    if duration_seconds <= 1.0:
        cap.release()
        return []

    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. 優先選取字幕含有觀音區關鍵字的時間點
    target_times: List[Tuple[float, str]] = []
    for item in timestamps:
        text = item.get("text", "")
        if any(kw in text for kw in GUANYIN_KEYWORDS):
            sec = item.get("start_seconds", 0.0)
            if 1.0 <= sec <= duration_seconds - 1.0:
                target_times.append((sec, text))

    # 2. 若關鍵字時間點不足，均勻分布取樣
    if len(target_times) < target_count:
        percentages = [0.15, 0.35, 0.55, 0.75, 0.90]
        for p in percentages:
            sec = duration_seconds * p
            if 0 < sec < duration_seconds:
                desc = "觀音區相關影片畫面"
                for item in timestamps:
                    if item.get("start_seconds", 0) <= sec <= item.get("end_seconds", 0):
                        desc = item.get("text", desc)
                        break
                target_times.append((sec, desc))

    # 去重時間過於接近的影格 (小於 3 秒)
    unique_targets: List[Tuple[float, str]] = []
    for sec, desc in sorted(target_times, key=lambda x: x[0]):
        if not any(abs(sec - u[0]) < 3.0 for u in unique_targets):
            unique_targets.append((sec, desc))
        if len(unique_targets) >= 5:
            break

    if not unique_targets and duration_seconds > 2.0:
        unique_targets.append((duration_seconds * 0.5, "影片重點畫面"))

    saved_images: List[Dict[str, Any]] = []
    idx = 1

    for sec, desc in unique_targets:
        frame_idx = int(sec * fps)
        cap.set(cv2.CAP_PROP_POS_FRAMES, min(frame_idx, total_frames - 1))
        ok, frame = cap.read()
        if not ok or frame is None:
            continue

        # 過濾純黑/過暗畫面 (灰階平均小於 15.0)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        if gray.mean() < 15.0:
            continue

        filename = f"{item_id}_frame_{idx:02d}.jpg"
        save_path = output_dir / filename
        cv2.imwrite(str(save_path), frame, [int(cv2.IMWRITE_JPEG_QUALITY), 90])

        saved_images.append({
            "path": f"images/{filename}",
            "filename": filename,
            "timestamp": format_seconds(sec),
            "seconds": round(sec, 2),
            "description": desc,
        })
        idx += 1
        if len(saved_images) >= target_count:
            break

    cap.release()
    return saved_images


def generate_markdown(record: Dict[str, Any]) -> str:
    """產出排版美觀的影片報告 Markdown (含截圖與時間軸逐字稿)。"""
    title = record.get("title") or record.get("id")
    channel = record.get("source_name") or "未知頻道"
    url = record.get("source_url") or ""
    status = record.get("crawl_status") or "已處理"
    crawled_at = record.get("crawled_at") or ""
    images = record.get("images", [])
    timestamps = record.get("timestamps", [])

    lines = [
        f"# {title}",
        "",
        "## 影片基本資訊",
        f"- **資料編號**：`{record.get('id')}`",
        f"- **頻道來源**：{channel}",
        f"- **原始網址**：[{url}]({url})",
        f"- **處理狀態**：{status}",
        f"- **擷取時間**：{crawled_at}",
        "",
        "## 代表性畫面截圖",
    ]

    if images:
        for img in images:
            img_rel = f"../{img['path']}"
            lines.append(f"### 畫面 [{img['timestamp']}] - {img['description']}")
            lines.append(f"![{img['description']}]({img_rel})\n")
    else:
        lines.append("*（未擷取畫面或無可用影像）*\n")

    lines.append("## 字幕逐字稿內容")
    if timestamps:
        for item in timestamps:
            tag = item.get("start", format_seconds(item.get("start_seconds", 0)))
            lines.append(f"- `[{tag}]` {item.get('text', '')}")
    else:
        lines.append("*（此影片無可用字幕軌或無法取得音訊）*")

    lines.append("")
    lines.append("## 清洗後完整文章段落")
    lines.append(record.get("content") or "無文字內容")
    lines.append("")

    return "\n".join(lines)


def update_index_jsonl(index_path: Path, record: Dict[str, Any]) -> None:
    """追加或更新資料至 output/index.jsonl (組員 4 共享知識庫格式)。"""
    index_path.parent.mkdir(parents=True, exist_ok=True)
    records: List[Dict[str, Any]] = []
    found = False

    if index_path.is_file():
        try:
            with open(index_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    item = json.loads(line)
                    if item.get("id") == record.get("id"):
                        records.append(record)
                        found = True
                    else:
                        records.append(item)
        except Exception:
            records = []

    if not found:
        records.append(record)

    with open(index_path, "w", encoding="utf-8") as f:
        for item in records:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")


def process_video(entry: Dict[str, Any], out_dir: str | Path = "output") -> Dict[str, Any]:
    """主處理函式：接收單筆 entry 字典並執行完整的 YouTube 影片字幕與畫面擷取流程。

    符合組員 1 crawler/main.py 規範：
      回傳包含 status, reason, http_status, final_url, title, source_name, html, links, attempts, elapsed_ms。
    同時產出組員 4 規格的 index.jsonl 以及 output/videos/{id}.json, output/videos/{id}.md, output/images/。
    """
    start_monotonic = time.monotonic()
    out = Path(out_dir)
    url = entry.get("url") or entry.get("source_url") or ""
    item_id = entry.get("id") or "video_unknown"

    vid = extract_video_id(url)
    if not vid:
        elapsed = round((time.monotonic() - start_monotonic) * 1000)
        return {
            "status": "failed",
            "reason": f"無效的 YouTube 網址: {url}",
            "http_status": "400",
            "final_url": url,
            "title": entry.get("title_hint", ""),
            "source_name": urlparse(url).hostname or "youtube.com",
            "html": "",
            "links": [url] if url else [],
            "attempts": 1,
            "elapsed_ms": elapsed,
        }

    # 若未指定 id 或為手動測試，則以 video_{vid} 為標準 id
    if item_id in ("manual_001", "video_unknown"):
        item_id = f"video_{vid}"

    work_dir = out.parent / "downloads" / vid if out.name == "output" else out / "downloads" / vid
    videos_dir = out / "videos"
    images_dir = out / "images"
    videos_dir.mkdir(parents=True, exist_ok=True)
    images_dir.mkdir(parents=True, exist_ok=True)

    status_code = "200"
    status_label = "success"
    reason_label = "OK"

    try:
        # 步驟 1: 使用 yt-dlp 下載中繼資料與字幕
        print(f"  [組員3影片模組] 開始下載與解析中繼資料: {vid} ({url})")
        download_video_and_metadata(url, work_dir)

        # 讀取中繼資料
        info_files = list(work_dir.glob("*.info.json"))
        meta: Dict[str, Any] = {}
        if info_files:
            meta = json.loads(info_files[0].read_text(encoding="utf-8", errors="replace"))

        title = meta.get("title") or entry.get("title_hint") or f"YouTube 影片 {vid}"
        channel = meta.get("channel") or meta.get("uploader") or (urlparse(url).hostname or "YouTube")

        # 步驟 2 (任務 4A): 字幕解析策略（優先官方/自動 .vtt，次選 Whisper）
        vtt_files = sorted(work_dir.glob("*.vtt"))
        timestamps: List[Dict[str, Any]] = []
        subtitle_source = "none"

        if vtt_files:
            # 優先挑選繁中、台灣、中文字幕
            preferred = next((f for f in vtt_files if any(k in f.name.lower() for k in ["zh-hant", "zh-tw", "zh"])), vtt_files[0])
            timestamps = parse_vtt(preferred)
            if timestamps:
                subtitle_source = f"youtube_vtt ({preferred.suffix})"
                print(f"    -> 成功解析 YouTube 字幕軌: {preferred.name} ({len(timestamps)} 段)")

        # 檢查下載的影音檔案
        media_files = sorted(work_dir.glob("*.mp4")) + sorted(work_dir.glob("*.mkv")) + sorted(work_dir.glob("*.webm"))
        media_path = media_files[0] if media_files else None

        # Fallback: 若無字幕軌且有影音檔，啟動 Whisper 語音轉錄
        if not timestamps and media_path and media_path.is_file():
            print("    -> 未找到線上字幕軌，自動啟動 Whisper 語音辨識轉錄...")
            try:
                timestamps = whisper_transcribe(media_path, model_name="base")
                subtitle_source = "whisper (base)"
                print(f"    -> Whisper 語音轉錄完成 ({len(timestamps)} 段)")
            except Exception as w_exc:
                print(f"    -> Whisper 轉錄未完成: {w_exc}")
                subtitle_source = f"whisper_failed ({w_exc})"

        # 步驟 3 (任務 4B): 智慧挑選 3～5 張代表性畫面
        saved_images: List[Dict[str, Any]] = []
        if media_path and media_path.is_file():
            saved_images = extract_representative_frames(
                video_path=media_path,
                output_dir=images_dir,
                item_id=item_id,
                timestamps=timestamps,
                target_count=4
            )
            print(f"    -> 已儲存 {len(saved_images)} 張代表性畫面至 output/images/")

        # 整合清洗後純文字內容
        full_content = "\n\n".join(
            re.sub(r"\s+", " ", seg["text"]).strip()
            for seg in timestamps
        ) if timestamps else "（無可用字幕逐字稿紀錄）"

        reason_label = f"OK ({subtitle_source})"
        crawl_status_str = f"success ({subtitle_source})" if timestamps else "success (no_subtitles)"

        # 步驟 4: 組員 4 共享資料結構 (index.jsonl)
        knowledge_record = {
            "id": item_id,
            "type": "video",
            "title": title,
            "source_url": url,
            "source_name": channel,
            "content": full_content,
            "images": saved_images,
            "links": [url],
            "timestamps": timestamps,
            "crawl_status": crawl_status_str,
            "crawled_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            "metadata": {
                "video_id": vid,
                "duration": meta.get("duration"),
                "view_count": meta.get("view_count"),
                "upload_date": meta.get("upload_date"),
            }
        }

        # 輸出 output/videos/{id}.json 與 {id}.md
        json_path = videos_dir / f"{item_id}.json"
        md_path = videos_dir / f"{item_id}.md"

        json_path.write_text(json.dumps(knowledge_record, ensure_ascii=False, indent=2), encoding="utf-8")
        md_content = generate_markdown(knowledge_record)
        md_path.write_text(md_content, encoding="utf-8")

        # 追加寫入 output/index.jsonl
        update_index_jsonl(out / "index.jsonl", knowledge_record)

        elapsed = round((time.monotonic() - start_monotonic) * 1000)

        # 回傳符合 crawler/main.py 的規範字典
        return {
            "status": status_label,
            "reason": reason_label,
            "http_status": status_code,
            "final_url": url,
            "title": title,
            "source_name": channel,
            "html": md_content,
            "links": [url],
            "attempts": 1,
            "elapsed_ms": elapsed,
        }

    except Exception as exc:
        elapsed = round((time.monotonic() - start_monotonic) * 1000)
        err_msg = str(exc)
        print(f"  [組員3影片模組] 處理影片失敗: {err_msg}")

        # 記錄失敗項目至 index.jsonl (保持組員 4 追蹤能力)
        failed_record = {
            "id": item_id,
            "type": "video",
            "title": entry.get("title_hint") or f"YouTube 影片 {vid}",
            "source_url": url,
            "source_name": urlparse(url).hostname or "YouTube",
            "content": "",
            "images": [],
            "links": [url],
            "timestamps": [],
            "crawl_status": f"failed: {err_msg}",
            "crawled_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        }
        update_index_jsonl(out / "index.jsonl", failed_record)

        return {
            "status": "failed",
            "reason": f"影片擷取失敗: {err_msg}",
            "http_status": "500",
            "final_url": url,
            "title": entry.get("title_hint", ""),
            "source_name": urlparse(url).hostname or "youtube.com",
            "html": "",
            "links": [url],
            "attempts": 1,
            "elapsed_ms": elapsed,
        }


def main() -> int:
    """CLI 入口：支援獨立批次或單一網址測試。"""
    parser = argparse.ArgumentParser(
        description="YouTube 影片字幕逐字稿與代表畫面擷取模組 (觀音區知識庫 - 組員 3)"
    )
    parser.add_argument("--url", help="單一 YouTube 影片網址 (方便現場抽測)")
    parser.add_argument("--id", help="指定資料代號 ID (搭配 --url 使用，如 page_026)")
    parser.add_argument("--urls", default="urls.csv", help="網址清單 CSV 檔案路徑 (預設 urls.csv)")
    parser.add_argument("--out-dir", default="output", help="輸出資料夾路徑 (預設 output)")
    parser.add_argument("--whisper-model", default="base", help="Whisper 辨識模型大小 (預設 base)")
    args = parser.parse_args()

    out_path = Path(args.out_dir)

    # 1. 單一網址測試模式
    if args.url:
        vid = extract_video_id(args.url)
        item_id = args.id or (f"video_{vid}" if vid else "manual_001")
        entry = {
            "id": item_id,
            "url": args.url,
            "type": "video",
            "origin": "manual",
            "topic": "觀音地方影像"
        }
        print(f"[組員3] 執行單一網址處理: {args.url}")
        res = process_video(entry, out_dir=out_path)
        print(f"[處理結果] 狀態: {res['status']}, 標題: {res['title']}, 耗時: {res['elapsed_ms']}ms")
        return 0 if res["status"] == "success" else 1

    # 2. 批次處理 urls.csv 中的 video 項目
    urls_file = Path(args.urls)
    if not urls_file.is_file():
        print(f"[錯誤] 找不到網址檔案: {urls_file}", file=sys.stderr)
        return 1

    with open(urls_file, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        video_entries = [r for r in reader if r.get("type") == "video"]

    print(f"[組員3] 在 {urls_file} 中找到 {len(video_entries)} 筆影片網址，開始批次處理...")
    success_count = 0

    for idx, e in enumerate(video_entries, 1):
        print(f"\n[{idx}/{len(video_entries)}] 正在處理 {e.get('id')}: {e.get('url')}")
        res = process_video(e, out_dir=out_path)
        if res["status"] == "success":
            success_count += 1

    print(f"\n[處理完成] 共處理 {len(video_entries)} 筆影片，成功: {success_count} 筆。")
    print(f"  - 知識庫索引: {out_path / 'index.jsonl'}")
    print(f"  - 影片報告資料夾: {out_path / 'videos'}")
    print(f"  - 代表截圖資料夾: {out_path / 'images'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
