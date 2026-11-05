"""YouTube Caption & Keyframe Pipeline for Guanyin District Knowledge Base.

期中專案 - 組員 3：YouTube 影片字幕與代表畫面擷取模組
對應老師任務 4、任務 5 與組員 4 的輸出資料標準。

功能特色：
  1. 輸入支援：
     - 單一 YouTube 網址 (方便老師現場抽測)
     - 網址文字檔 (.txt, .csv)
     - Word 講義檔 (.docx，自動原生解析出 YT 連結)
     - 標準輸入 (管道 stdin)
  2. 字幕優先順序：
     - 優先使用 YouTube 官方字幕或自動生成字幕 (.vtt)
     - 若無字幕，自動 fallback 至 Whisper 語音辨識 (faster-whisper 或 whisper)
     - 支援 OCR 辨識影片底部內嵌字 (可選)
  3. 代表畫面擷取 (任務 4B)：
     - 自動選取 3~5 張代表性畫面 (優先依據觀音區關鍵字時間點或均勻影格)
     - 避開純黑畫面 (黑屏過濾)
     - 儲存為 JPG 圖片至 output/images/ 並記錄時間戳記與描述
  4. 整合輸出 (任務 5 / 組員 4 格式)：
     - output/index.jsonl (追加模式，含 id, type, title, content, images, timestamps...)
     - output/crawl_report.csv (爬取狀態與耗時報表)
     - output/videos/{video_id}.json (單片詳細結構化資料)
     - output/videos/{video_id}.md (人類可讀的 Markdown 報表，含截圖與時間軸)
"""

from __future__ import annotations

import argparse
import csv
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

# 避免 Windows 終端編碼導致 print 報錯
if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from youtube_link_filter import extract_video_id, find_youtube_video_links, read_source_text

# 觀音區景點與文化關鍵字 (用於代表畫面優先挑選)
GUANYIN_KEYWORDS = [
    "觀音", "白沙岬", "燈塔", "草漯", "沙丘", "甘泉寺", "向陽", "農場",
    "蓮花", "風車", "濱海", "大潭", "新屋", "文化", "藻礁", "寺廟", "景點"
]


def format_seconds(seconds: float) -> str:
    """Format seconds into HH:MM:SS or MM:SS string."""
    seconds = max(0.0, seconds)
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def parse_vtt_timestamp(ts_str: str) -> float:
    """Convert VTT timestamp (HH:MM:SS.mmm or MM:SS.mmm) to seconds."""
    parts = ts_str.strip().split(":")
    if len(parts) == 3:
        h, m, s = parts
        return int(h) * 3600 + int(m) * 60 + float(s)
    elif len(parts) == 2:
        m, s = parts
        return int(m) * 60 + float(s)
    return 0.0


def parse_vtt(path: Path) -> list[dict[str, Any]]:
    """Parse a WebVTT subtitle file into structured segments."""
    if not path.is_file():
        return []

    text = path.read_text(encoding="utf-8", errors="replace")
    blocks = re.split(r"\n\s*\n", text)
    rows: list[dict[str, Any]] = []

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
        # Remove HTML tags (e.g. <c>, </c>)
        body = re.sub(r"<[^>]+>", "", body).strip()

        if body:
            # Deduplicate consecutive identical lines (common in rolling auto-subs)
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


def run_ytdlp(url: str, work: Path) -> dict[str, Any]:
    """Download video, metadata, and subtitles via yt-dlp."""
    work.mkdir(parents=True, exist_ok=True)
    template = str(work / "%(id)s.%(ext)s")

    yt_command = [
        sys.executable, "-m", "yt_dlp",
        "--no-playlist",
        "--write-info-json",
        "--write-subs",
        "--write-auto-subs",
        "--sub-langs", "zh.*,en.*,all",
        "--sub-format", "vtt/best",
        "-f", "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/best",
        "--merge-output-format", "mp4",
        "-o", template,
        url,
    ]

    try:
        result = subprocess.run(yt_command, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            # Try plain yt-dlp executable if python -m yt_dlp failed
            plain_cmd = ["yt-dlp"] + yt_command[3:]
            result = subprocess.run(plain_cmd, capture_output=True, text=True, check=False)
            if result.returncode != 0:
                err_msg = result.stderr[-2000:] if result.stderr else result.stdout[-2000:]
                raise RuntimeError(err_msg.strip() or "yt-dlp 下載失敗")
        return {"stdout": result.stdout, "stderr": result.stderr}
    except FileNotFoundError:
        raise RuntimeError("系統中未找到 yt-dlp，請先執行: pip install yt-dlp")


def whisper_transcribe(audio_or_video: Path, model_name: str = "base") -> list[dict[str, Any]]:
    """Transcribe audio/video using faster-whisper or standard whisper."""
    # 1. Try faster-whisper first
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

    # 2. Try openai whisper
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
        raise RuntimeError("未安裝語音辨識套件 (可安裝 faster-whisper 或 openai-whisper)")


def extract_representative_frames(
    video_path: Path,
    output_dir: Path,
    video_id: str,
    timestamps: list[dict[str, Any]],
    target_count: int = 4
) -> list[dict[str, Any]]:
    """Select and save 3~5 representative frames with timestamps and descriptions."""
    try:
        import cv2
    except ImportError:
        print("  [提示] 未安裝 opencv-python，跳過畫面截圖步驟 (可透過 pip install opencv-python 啟用)")
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

    # 1. Prioritize timestamps containing Guanyin keywords
    target_times: list[Tuple[float, str]] = []
    for item in timestamps:
        text = item.get("text", "")
        if any(kw in text for kw in GUANYIN_KEYWORDS):
            sec = item.get("start_seconds", 0.0)
            if 1.0 <= sec <= duration_seconds - 1.0:
                target_times.append((sec, text))

    # 2. If not enough keyword frames, distribute evenly across duration
    if len(target_times) < target_count:
        percentages = [0.15, 0.35, 0.55, 0.75, 0.90]
        for p in percentages:
            sec = duration_seconds * p
            if 0 < sec < duration_seconds:
                # Find matching subtitle text near this time
                desc = "觀音區相關影片畫面"
                for item in timestamps:
                    if item.get("start_seconds", 0) <= sec <= item.get("end_seconds", 0):
                        desc = item.get("text", desc)
                        break
                target_times.append((sec, desc))

    # Deduplicate times that are too close (within 3 seconds)
    unique_targets: list[Tuple[float, str]] = []
    for sec, desc in sorted(target_times, key=lambda x: x[0]):
        if not any(abs(sec - u[0]) < 3.0 for u in unique_targets):
            unique_targets.append((sec, desc))
        if len(unique_targets) >= 5:
            break

    # If still empty, add mid-point
    if not unique_targets and duration_seconds > 2.0:
        unique_targets.append((duration_seconds * 0.5, "影片重點畫面"))

    saved_images: list[dict[str, Any]] = []
    idx = 1

    for sec, desc in unique_targets:
        frame_idx = int(sec * fps)
        cap.set(cv2.CAP_PROP_POS_FRAMES, min(frame_idx, total_frames - 1))
        ok, frame = cap.read()
        if not ok or frame is None:
            continue

        # Check for pure black/blank frames (mean brightness threshold)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        if gray.mean() < 15.0:
            continue

        filename = f"{video_id}_frame_{idx:02d}.jpg"
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


def ocr_burned_in_subtitles(video_path: Path, sample_seconds: float = 2.0) -> list[dict[str, Any]]:
    """OCR the lower portion of video frames for burned-in subtitles."""
    try:
        import cv2
        import pytesseract
    except ImportError:
        return []

    if not video_path.is_file():
        return []

    cap = cv2.VideoCapture(str(video_path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    step = max(1, int(fps * sample_seconds))
    rows: list[dict[str, Any]] = []

    for frame_no in range(0, total, step):
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_no)
        ok, frame = cap.read()
        if not ok:
            continue

        # OCR bottom 45% of the frame
        crop = frame[int(frame.shape[0] * 0.55):, :]
        try:
            text = pytesseract.image_to_string(crop, lang="chi_tra+eng", config="--psm 6").strip()
            text = " ".join(text.split())
        except Exception:
            break

        if not text or len(text) < 2:
            continue

        start_sec = round(frame_no / fps, 3)
        if rows and rows[-1]["text"] == text and start_sec - rows[-1]["end_seconds"] <= sample_seconds * 1.5:
            rows[-1]["end_seconds"] = start_sec
        else:
            rows.append({
                "start": format_seconds(start_sec),
                "end": format_seconds(start_sec + sample_seconds),
                "start_seconds": start_sec,
                "end_seconds": start_sec + sample_seconds,
                "text": text
            })

    cap.release()
    return rows


def format_markdown_report(record: dict[str, Any]) -> str:
    """Format full video data into a clean, human-readable Markdown report."""
    vid = record["video_id"]
    title = record.get("title") or vid
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
        f"- **影片編號**：`{record['id']}` (`{vid}`)",
        f"- **頻道來源**：{channel}",
        f"- **原始網址**：[{url}]({url})",
        f"- **處理狀態**：{status}",
        f"- **擷取時間**：{crawled_at}",
        "",
        "## 代表性畫面截圖",
    ]

    if images:
        for img in images:
            img_md_path = f"../{img['path']}"
            lines.append(f"### 畫面 [{img['timestamp']}] - {img['description']}")
            lines.append(f"![{img['description']}]({img_md_path})")
            lines.append("")
    else:
        lines.append("*（未擷取畫面或無可用影像）*\n")

    lines.append("## 字幕逐字稿內容")
    if timestamps:
        for item in timestamps:
            time_tag = item.get("start", format_seconds(item.get("start_seconds", 0)))
            lines.append(f"- `[{time_tag}]` {item.get('text', '')}")
    else:
        lines.append("*（此影片無可用字幕或無法取得音訊）*")

    lines.append("")
    lines.append("## 清洗後完整文章段落")
    lines.append(record.get("content") or "無文字內容")
    lines.append("")

    return "\n".join(lines)


def process_single_video(url: str, root: Path, whisper_model: str = "base") -> dict[str, Any]:
    """Process a single YouTube video end-to-end and output artifacts."""
    vid = extract_video_id(url)
    if not vid:
        return {"video_id": "unknown", "status": "error", "reason": f"無效的 YouTube 網址: {url}"}

    print("\n" + "=" * 50)
    print(f"[處理開始] YouTube 影片 ID: {vid}")
    print(f"  來源網址: {url}")
    print("=" * 50)

    start_time = time.time()
    work_dir = root / "downloads" / vid
    videos_dir = root / "output" / "videos"
    images_dir = root / "output" / "images"
    videos_dir.mkdir(parents=True, exist_ok=True)
    images_dir.mkdir(parents=True, exist_ok=True)

    status_str = "成功"
    subtitle_source = "not_found"

    try:
        # 1. Download metadata, subtitles, and video via yt-dlp
        print("  [步驟 1/4] 下載影片基本資料與字幕...")
        run_ytdlp(url, work_dir)

        # Read yt-dlp metadata
        info_files = list(work_dir.glob("*.info.json"))
        meta: dict[str, Any] = {}
        if info_files:
            meta = json.loads(info_files[0].read_text(encoding="utf-8", errors="replace"))

        title = meta.get("title") or f"YouTube 影片 {vid}"
        channel = meta.get("channel") or meta.get("uploader") or "YouTube 頻道"

        # 2. Check for official/auto subtitles (.vtt)
        print("  [步驟 2/4] 檢查與解析字幕...")
        vtt_files = sorted(work_dir.glob("*.vtt"))
        timestamps: list[dict[str, Any]] = []

        if vtt_files:
            preferred_vtt = next((f for f in vtt_files if "zh" in f.name.lower()), vtt_files[0])
            timestamps = parse_vtt(preferred_vtt)
            if timestamps:
                subtitle_source = f"youtube_subtitle ({preferred_vtt.suffix})"
                print(f"    -> 成功取得 YouTube 官方/自動字幕軌 ({len(timestamps)} 段)")

        # 3. Fallback to Whisper if no subtitle found
        video_files = sorted(work_dir.glob("*.mp4")) + sorted(work_dir.glob("*.mkv")) + sorted(work_dir.glob("*.webm"))
        video_path = video_files[0] if video_files else None

        if not timestamps:
            if video_path and video_path.is_file():
                print("    -> 未找到線上字幕，啟動 Whisper 語音轉錄...")
                try:
                    timestamps = whisper_transcribe(video_path, whisper_model)
                    subtitle_source = f"whisper ({whisper_model})"
                    print(f"    -> Whisper 轉錄完成 ({len(timestamps)} 段)")
                except Exception as exc:
                    print(f"    -> Whisper 轉錄失敗或未安裝: {exc}")
                    subtitle_source = f"whisper_failed: {exc}"
            else:
                subtitle_source = "no_video_stream"

        # 4. Extract representative frames (Task 4B)
        print("  [步驟 3/4] 擷取代表性畫面 (3~5 張)...")
        saved_images: list[dict[str, Any]] = []
        if video_path and video_path.is_file():
            saved_images = extract_representative_frames(
                video_path=video_path,
                output_dir=images_dir,
                video_id=vid,
                timestamps=timestamps,
                target_count=4
            )
            print(f"    -> 已擷取 {len(saved_images)} 張代表畫面至 output/images/")
        else:
            print("    -> 提示: 無影片檔可供截圖")

        # 5. Full text synthesis
        full_content = "\n\n".join(
            re.sub(r"\s+", " ", seg["text"]).strip()
            for seg in timestamps
        ) if timestamps else "（無文字字幕紀錄）"

        if not timestamps:
            status_str = f"無字幕 ({subtitle_source})"
        else:
            status_str = f"成功 ({subtitle_source})"

        # 6. Standardized Record (Matching Member 4 Schema)
        record = {
            "id": f"video_{vid}",
            "type": "video",
            "video_id": vid,
            "title": title,
            "source_url": url,
            "source_name": channel,
            "content": full_content,
            "images": saved_images,
            "links": [url],
            "timestamps": timestamps,
            "crawl_status": status_str,
            "crawled_at": datetime.now(timezone.utc).isoformat(),
            "metadata": {
                "duration": meta.get("duration"),
                "view_count": meta.get("view_count"),
                "upload_date": meta.get("upload_date"),
                "description": meta.get("description", "")[:500],
            }
        }

        # 7. Write outputs
        print("  [步驟 4/4] 輸出結構化資料與 Markdown...")
        json_path = videos_dir / f"{vid}.json"
        md_path = videos_dir / f"{vid}.md"

        json_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        md_report = format_markdown_report(record)
        md_path.write_text(md_report, encoding="utf-8")

        # Append to index.jsonl (Team shared knowledge base)
        index_jsonl = root / "output" / "index.jsonl"
        with open(index_jsonl, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

        cost_time = round(time.time() - start_time, 2)
        print(f"[完成] 影片 {vid} 處理成功！耗時 {cost_time} 秒")
        print(f"  -> JSON: {json_path}")
        print(f"  -> Markdown: {md_path}")

        return {
            "video_id": vid,
            "title": title,
            "url": url,
            "status": "ok",
            "crawl_status": status_str,
            "subtitle_count": len(timestamps),
            "image_count": len(saved_images),
            "cost_time": cost_time,
        }

    except Exception as exc:
        cost_time = round(time.time() - start_time, 2)
        err_msg = str(exc)
        print(f"[失敗] 處理發生例外: {err_msg}")

        failed_record = {
            "id": f"video_{vid}",
            "type": "video",
            "video_id": vid,
            "title": f"YouTube 影片 {vid}",
            "source_url": url,
            "source_name": "YouTube",
            "content": "",
            "images": [],
            "links": [url],
            "timestamps": [],
            "crawl_status": f"失敗: {err_msg}",
            "crawled_at": datetime.now(timezone.utc).isoformat(),
        }

        index_jsonl = root / "output" / "index.jsonl"
        with open(index_jsonl, "a", encoding="utf-8") as f:
            f.write(json.dumps(failed_record, ensure_ascii=False) + "\n")

        return {
            "video_id": vid,
            "title": vid,
            "url": url,
            "status": "error",
            "crawl_status": f"失敗: {err_msg}",
            "subtitle_count": 0,
            "image_count": 0,
            "cost_time": cost_time,
        }


def update_crawl_report(report_path: Path, results: list[dict[str, Any]]) -> None:
    """Write/append processing summary to crawl_report.csv."""
    report_path.parent.mkdir(parents=True, exist_ok=True)
    file_exists = report_path.is_file()

    headers = ["video_id", "title", "url", "crawl_status", "subtitle_count", "image_count", "cost_seconds", "crawled_at"]
    rows = []
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    for r in results:
        rows.append([
            r.get("video_id", ""),
            r.get("title", ""),
            r.get("url", ""),
            r.get("crawl_status", ""),
            r.get("subtitle_count", 0),
            r.get("image_count", 0),
            r.get("cost_time", 0.0),
            now_str,
        ])

    with open(report_path, "a", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(headers)
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="YouTube 影片字幕與代表畫面自動化處理管道 (桃園市觀音區地方知識爬蟲 - 組員 3)"
    )
    parser.add_argument(
        "input",
        nargs="?",
        default="resource.20260921.docx",
        help="輸入來源：可為單一 YouTube 網址、.docx 文件、.txt/.csv 網址清單、或 '-' 代表標準輸入 (預設讀取 resource.20260921.docx)",
    )
    parser.add_argument(
        "--root",
        default=".",
        help="專案根目錄或輸出目錄 (預設為當前目錄)",
    )
    parser.add_argument(
        "--whisper-model",
        default="base",
        choices=["tiny", "base", "small", "medium", "large"],
        help="Whisper 語音辨識模型大小 (預設 base)",
    )
    args = parser.parse_args()

    root_dir = Path(args.root)

    # 1. Extract source text and find YouTube links
    source_text = read_source_text(args.input)
    links = find_youtube_video_links(source_text)

    # If user provided a direct YouTube URL that didn't get matched by find_youtube_video_links
    if not links:
        single_vid = extract_video_id(args.input)
        if single_vid:
            links = [{"video_id": single_vid, "url": args.input}]

    if not links:
        print(f"[錯誤] 在輸入來源 '{args.input}' 中未找到任何可處理的 YouTube 影片網址！", file=sys.stderr)
        return 1

    print(f"[準備就緒] 共找到 {len(links)} 部 YouTube 影片，開始執行管線...")
    for idx, item in enumerate(links, 1):
        print(f"  {idx}. [{item['video_id']}] {item['url']}")

    # 2. Process each video
    results: list[dict[str, Any]] = []
    for item in links:
        res = process_single_video(item["url"], root_dir, args.whisper_model)
        results.append(res)

    # 3. Update summary report
    report_csv = root_dir / "output" / "crawl_report.csv"
    update_crawl_report(report_csv, results)

    print("\n" + "=" * 50)
    print("[處理完畢] 所有影片已處理完成！")
    print(f"- 知識庫索引: {root_dir / 'output' / 'index.jsonl'}")
    print(f"- 爬取統計報表: {report_csv}")
    print(f"- 影片結構化資料: {root_dir / 'output' / 'videos'}")
    print(f"- 代表畫面截圖庫: {root_dir / 'output' / 'images'}")
    print("=" * 50)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
