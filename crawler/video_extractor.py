"""YouTube Video Extractor with Multi-Track Caption Arbitration.

期中專案 - 組員 3：YouTube 影片字幕逐字稿、多軌比對仲裁與代表畫面擷取模組
對應任務 4A（字幕與語音多模態比對）、4B（代表畫面擷取）與任務 5/6（資料整合與品質查證）。

核心架構特色：
  1. 多軌並行擷取 (Multi-Track Caption Pipeline)：
     - 軌道 A：YouTube 官方 / 自動生成字幕 (.vtt)
     - 軌道 B：音軌語音辨識 (faster-whisper，含防幻覺/防跳針參數)
     - 軌道 C：影片畫面底部 OCR 辨識 (OpenCV 裁切 + Tesseract 繁中辨識)
  2. 智慧品質評分與仲裁引擎 (Caption Arbitrator)：
     - 計算中文字元比例 (過濾純英文歌 BGM)
     - 計算重複詞跳針懲罰 (終結客家話/雜訊引起的「腮筒」、「一秒鐘」無限跳針)
     - 觀音區地方知識關鍵字命中加權 (草漯、白沙岬、崙坪、甘泉寺等)
     - 自動推選最優版本，或標記 audio_bgm_only / needs_review
  3. 人工審核 (Human-in-the-Loop) 與 LLM 對照支援：
     - 在 output/videos/{id}.md 中生成清晰的「三軌品質評分對照表」與各版本摘要
     - 支援手動指定覆寫 (manual override)
  4. 產出完全相容組員 4 的 output/index.jsonl 規範。
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

# Windows 終端編碼保護 (避免 cp950 遇到特殊符號報錯)
if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# 修復 Python 3.13 下 tarfile 不接受 metadata_errors 導致 faster-whisper 下載崩潰的問題
try:
    import tarfile
    _orig_tarfile_open = tarfile.open
    def _safe_tarfile_open(*args, **kwargs):
        kwargs.pop("metadata_errors", None)
        return _orig_tarfile_open(*args, **kwargs)
    tarfile.open = _safe_tarfile_open
    if hasattr(tarfile, "TarFile") and hasattr(tarfile.TarFile, "open"):
        _orig_tarfile_cls_open = tarfile.TarFile.open
        def _safe_tarfile_cls_open(*args, **kwargs):
            kwargs.pop("metadata_errors", None)
            return _orig_tarfile_cls_open(*args, **kwargs)
        tarfile.TarFile.open = _safe_tarfile_cls_open
except Exception:
    pass

_DEPENDENCIES_CHECKED = False

def ensure_runtime_dependencies() -> None:
    """自動偵測組員環境相依套件，若缺漏自動嘗試在目前 Python 環境中安裝 (免除手動安裝困擾)。"""
    global _DEPENDENCIES_CHECKED
    if _DEPENDENCIES_CHECKED:
        return
    _DEPENDENCIES_CHECKED = True

    required_packages = [
        ("yt_dlp", "yt-dlp"),
        ("cv2", "opencv-python"),
        ("av", "av"),
        ("whisper", "openai-whisper"),
        ("rapidocr_onnxruntime", "rapidocr-onnxruntime"),
    ]
    missing = []
    for mod_name, pkg_name in required_packages:
        try:
            __import__(mod_name)
        except ImportError:
            missing.append(pkg_name)

    if missing:
        print(f"\n[組員3影片模組] 🛠️ 偵測到目前環境缺少套件: {missing}")
        print(f"[組員3影片模組] 正在自動為您安裝，請稍候片刻...")
        try:
            cmd = [sys.executable, "-m", "pip", "install"] + missing
            subprocess.run(cmd, check=True)
            print("[組員3影片模組] ✅ 相依套件自動安裝完成！繼續執行任務...\n")
        except Exception as exc:
            print(f"[組員3影片模組] ⚠️ 自動安裝未完成 ({exc})，將嘗試以既有環境降級運作。\n")

# 觀音區景點與文化關鍵字 (用於代表畫面優先挑選與字幕品質評分)
GUANYIN_KEYWORDS = [
    "觀音", "白沙岬", "燈塔", "草漯", "沙丘", "甘泉寺", "向陽", "農場",
    "蓮花", "風車", "濱海", "大潭", "新屋", "文化", "藻礁", "寺廟", "景點",
    "guanyin", "kuangin", "hakka", "崙坪", "客家", "地景"
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
    """使用 yt-dlp 下載影片、字幕與 info.json 中繼資料 (優先原生 Python API)。"""
    work_dir.mkdir(parents=True, exist_ok=True)
    template = str(work_dir / "%(id)s.%(ext)s")

    has_ffmpeg = ensure_ffmpeg()
    # 若系統無 ffmpeg，下載 pre-merged 影音檔或單獨音訊，避免無法合併
    fmt = "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/best" if has_ffmpeg else "best[ext=mp4]/b/best"

    # 1. 優先嘗試直接使用 yt_dlp Python API
    api_exc = None
    try:
        import yt_dlp
        ydl_opts = {
            "outtmpl": template,
            "format": fmt,
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": ["zh-Hant", "zh-TW", "zh", "en", "all"],
            "subtitlesformat": "vtt",
            "writeinfojson": True,
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "extractor_args": {
                "youtube": {
                    "player_client": ["android", "ios", "mweb", "web"],
                }
            },
        }
        if has_ffmpeg:
            ydl_opts["merge_output_format"] = "mp4"

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            return {"info": info}
    except ImportError:
        pass
    except Exception as exc:
        api_exc = exc
        print(f"     [提示] yt_dlp API 下載遭遇例外，嘗試命令列 fallback: {exc}")

    # 2. 次選 subprocess 命令列方式
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "--no-playlist",
        "--write-info-json",
        "--write-subs",
        "--write-auto-subs",
        "--sub-langs", "zh.*,en.*,all",
        "--sub-format", "vtt/best",
        "-f", fmt,
        "--extractor-args", "youtube:player_client=android,ios,mweb,web",
        "-o", template,
        url,
    ]
    if has_ffmpeg:
        cmd.extend(["--merge-output-format", "mp4"])

    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if res.returncode != 0:
            err = res.stderr[-2000:] if res.stderr else res.stdout[-2000:]
            if not err.strip() and api_exc:
                err = str(api_exc)
            raise RuntimeError(f"yt-dlp 下載失敗: {err.strip()}")
        return {"stdout": res.stdout, "stderr": res.stderr}
    except FileNotFoundError:
        raise RuntimeError("Python 環境中未找到 yt_dlp 模組，請執行: pip install --upgrade yt-dlp")


def configure_tesseract() -> bool:
    """自動尋找 Windows 上的 Tesseract-OCR 執行檔。"""
    try:
        import pytesseract
        import shutil
        if shutil.which("tesseract"):
            return True
        candidates = [
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"),
            os.path.expandvars(r"%ProgramW6432%\Tesseract-OCR\tesseract.exe"),
        ]
        for c in candidates:
            if os.path.isfile(c):
                pytesseract.pytesseract.tesseract_cmd = c
                return True
        return False
    except ImportError:
        return False


def ensure_ffmpeg() -> bool:
    """確保 ffmpeg.exe 可正常執行，若無則自動尋找 imageio-ffmpeg 或常見目錄。"""
    import shutil
    try:
        import imageio_ffmpeg
        ffmpeg_bin = imageio_ffmpeg.get_ffmpeg_exe()
        if os.path.isfile(ffmpeg_bin):
            bin_dir = os.path.dirname(ffmpeg_bin)
            if bin_dir not in os.environ.get("PATH", ""):
                os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")
    except Exception:
        pass

    # 實體測試 ffmpeg 是否真正可用
    try:
        res = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True, check=False)
        return res.returncode == 0
    except Exception:
        return False


def load_audio_without_ffmpeg(file_path: str, sr: int = 16000):
    """使用 PyAV (av) 解碼音訊為 16kHz float32 mono，不依賴系統 PATH 中的 ffmpeg.exe。"""
    import av
    import numpy as np

    path_obj = Path(file_path)
    target_path = file_path

    # 若傳入的檔案無音軌 (如 yt-dlp 分離下載的純視訊 mp4)，自動尋找同目錄下的 m4a / webm / mp3
    try:
        container = av.open(target_path)
        audio_streams = [s for s in container.streams if s.type == "audio"]
        container.close()
    except Exception:
        audio_streams = []

    if not audio_streams:
        for ext in [".m4a", ".mp3", ".wav", ".aac", ".opus", ".webm"]:
            for alt in path_obj.parent.glob(f"*{ext}"):
                try:
                    alt_cont = av.open(str(alt))
                    if any(s.type == "audio" for s in alt_cont.streams):
                        alt_cont.close()
                        print(f"     [提示] 視訊檔無音軌，自動切換至同目錄音訊檔: {alt.name}")
                        target_path = str(alt)
                        break
                    alt_cont.close()
                except Exception:
                    continue
            if target_path != file_path:
                break

    container = av.open(target_path)
    audio_streams = [s for s in container.streams if s.type == "audio"]
    if not audio_streams:
        container.close()
        return np.zeros(0, dtype=np.float32)

    stream = audio_streams[0]
    resampler = av.AudioResampler(format="fltp", layout="mono", rate=sr)
    chunks = []

    for frame in container.decode(stream):
        for resampled_frame in resampler.resample(frame):
            arr = resampled_frame.to_ndarray()
            chunks.append(arr[0])

    container.close()
    if not chunks:
        return np.zeros(0, dtype=np.float32)
    return np.concatenate(chunks).astype(np.float32)


def whisper_transcribe(audio_or_video: Path, model_name: str = "base") -> List[Dict[str, Any]]:
    """若無線上字幕，使用 faster-whisper（或 whisper）轉錄音軌。

    關鍵防禦：
      - 純 Python 音訊解碼：使用 PyAV 直接解出 16kHz float32 音訊，零依賴系統 ffmpeg.exe。
      - condition_on_previous_text=False：徹底打碎客家話或音樂引起的「腮筒」「一秒鐘」無限重複跳針。
      - no_speech_threshold=0.6：純音樂片段自動視為靜音，不硬猜歌詞。
    """
    import numpy as np
    last_error = None

    # 1. 音訊解碼預備 (自動避開系統缺 ffmpeg 的 WinError 2)
    has_ffmpeg = ensure_ffmpeg()
    audio_input: Any = str(audio_or_video)
    if not has_ffmpeg:
        print("     [提示] 系統無可用 ffmpeg.exe，啟用純 Python (PyAV) 解碼音軌串流...")
        try:
            audio_input = load_audio_without_ffmpeg(str(audio_or_video))
            print(f"     [音軌] 音訊解碼完成 (長度: {len(audio_input)/16000:.1f} 秒)")
        except Exception as dec_err:
            print(f"     [警告] PyAV 解碼音訊異常: {dec_err}，嘗試以原路徑傳入")
            audio_input = str(audio_or_video)

    # 2. 優先嘗試 standard openai-whisper (如果已安裝)
    try:
        import whisper
        print("     -> 啟動官方 openai-whisper 進行音軌轉錄...")
        model = whisper.load_model(model_name)
        res = model.transcribe(
            audio_input,
            condition_on_previous_text=False,
            no_speech_threshold=0.6,
            fp16=False,
        )
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
        if results:
            return results
    except ImportError:
        pass
    except Exception as exc:
        last_error = exc

    # 3. 次選 faster-whisper
    try:
        from faster_whisper import WhisperModel
        model = None
        for c_type in ("default", "float32", "int8"):
            try:
                model = WhisperModel(model_name, device="cpu", compute_type=c_type)
                break
            except Exception:
                continue
        if model is None:
            model = WhisperModel(model_name, device="auto")

        segments, _ = model.transcribe(
            audio_input,
            vad_filter=False,
            condition_on_previous_text=False,
            no_speech_threshold=0.6,
        )
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
        if results:
            return results
    except Exception as exc:
        last_error = exc

    if last_error:
        import traceback
        err_str = str(last_error)
        print("     [除錯詳細資訊] Whisper 異常追蹤:")
        traceback.print_exception(type(last_error), last_error, last_error.__traceback__)
        raise RuntimeError(f"語音辨識執行錯誤: {err_str}")

    raise RuntimeError("未安裝語音辨識套件 (可安裝 faster-whisper 或 openai-whisper)")


def ocr_burned_in_subtitles(video_path: Path, sample_seconds: float = 1.5) -> List[Dict[str, Any]]:
    """從影片畫面下方 35% 裁切區域進行 OCR，擷取內嵌硬字幕 (專門解客家話/電視節目字幕條)。"""
    try:
        import cv2
    except ImportError:
        print("     [提示] 虛擬環境未安裝 opencv-python，跳過 OCR 辨識")
        return []

    # 1. 優先嘗試 RapidOCR (純 Python ONNX 引擎，原生支援中文，免安裝任何外部 exe 軟體)
    rapid_engine = None
    try:
        from rapidocr_onnxruntime import RapidOCR
        rapid_engine = RapidOCR()
        print("     -> 啟動 RapidOCR (ONNX) 畫面繁中硬字幕辨識引擎...")
    except ImportError:
        pass

    # 2. 次選 Tesseract-OCR
    tesseract_available = False
    use_lang = "eng"
    if rapid_engine is None:
        try:
            import pytesseract
            if configure_tesseract():
                avail_langs = pytesseract.get_languages()
                if "chi_tra" in avail_langs:
                    use_lang = "chi_tra+eng" if "eng" in avail_langs else "chi_tra"
                    tesseract_available = True
                elif "chi_sim" in avail_langs:
                    use_lang = "chi_sim+eng" if "eng" in avail_langs else "chi_sim"
                    tesseract_available = True
                else:
                    use_lang = "eng"
                    tesseract_available = True
            else:
                print("     [提示] 系統未安裝 Tesseract-OCR 軟體 (tesseract.exe)。")
                print("     👉 建議直接在虛擬環境安裝免裝外部軟體的 RapidOCR: .\\.venv\\Scripts\\python.exe -m pip install rapidocr-onnxruntime")
                return []
        except ImportError:
            print("     [提示] 未安裝 OCR 套件，建議執行: .\\.venv\\Scripts\\python.exe -m pip install rapidocr-onnxruntime")
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

    step = max(1, int(fps * sample_seconds))
    rows: List[Dict[str, Any]] = []

    for frame_no in range(0, total_frames, step):
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_no)
        ok, frame = cap.read()
        if not ok or frame is None:
            continue

        # 裁切畫面下方 35% (字幕主要落在 65% ~ 95% 區間)
        h, w = frame.shape[:2]
        crop = frame[int(h * 0.65):int(h * 0.95), :]

        text = ""
        if rapid_engine is not None:
            try:
                res, _ = rapid_engine(crop)
                if res:
                    text = " ".join([line[1].strip() for line in res if line[2] >= 0.5])
            except Exception:
                continue
        elif tesseract_available:
            try:
                import pytesseract
                text = pytesseract.image_to_string(crop, lang=use_lang, config="--psm 6").strip()
                text = " ".join(text.split())
                if not text:
                    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
                    _, thresh = cv2.threshold(gray, 180, 255, cv2.THRESH_BINARY)
                    text = pytesseract.image_to_string(thresh, lang=use_lang, config="--psm 6").strip()
                    text = " ".join(text.split())
            except Exception:
                continue

        chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
        if chinese_chars < 2:
            continue

        start_sec = round(frame_no / fps, 3)
        if rows and rows[-1]["text"] == text and start_sec - rows[-1]["end_seconds"] <= sample_seconds * 1.5:
            rows[-1]["end_seconds"] = round(start_sec + sample_seconds, 3)
        else:
            rows.append({
                "start": format_seconds(start_sec),
                "end": format_seconds(start_sec + sample_seconds),
                "start_seconds": start_sec,
                "end_seconds": round(start_sec + sample_seconds, 3),
                "text": text
            })

    cap.release()
    return rows


# =========================================================================
# 多軌比對與智慧仲裁引擎 (Multi-Track Caption Arbitrator)
# =========================================================================

def evaluate_caption_quality(segments: List[Dict[str, Any]]) -> Dict[str, Any]:
    """計算字幕軌道的品質分數與統計特徵：

    - 中文字元比例 (chinese_ratio)
    - 英文單字比例 (english_ratio)
    - 重複詞跳針率 (duplicate_ratio) -> 偵測「腮筒*57」或「一秒鐘*13」
    - 觀音關鍵字命中次數 (keyword_hits)
    - 綜合品質分數 (score: 0 ~ 100)
    """
    if not segments:
        return {
            "score": 0.0,
            "segments_count": 0,
            "chinese_ratio": 0.0,
            "english_ratio": 0.0,
            "duplicate_ratio": 0.0,
            "keyword_hits": 0,
            "top_repeated": "",
            "preview": "（無內容）",
        }

    full_text = " ".join(s.get("text", "") for s in segments)
    total_len = len(full_text)
    if total_len == 0:
        return {"score": 0.0, "segments_count": 0, "preview": "（空內容）"}

    # 1. 語言比例
    chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", full_text))
    english_words = len(re.findall(r"[A-Za-z]+", full_text))
    chinese_ratio = round(chinese_chars / max(1, total_len), 3)
    english_ratio = round(english_words * 4 / max(1, total_len), 3)

    # 2. 重複詞跳針檢測 (偵測 2~4 字的連續高頻短語)
    text_list = [s.get("text", "").strip() for s in segments if s.get("text", "").strip()]
    phrase_counts: Dict[str, int] = {}
    for t in text_list:
        phrase_counts[t] = phrase_counts.get(t, 0) + 1

    max_repeat_count = max(phrase_counts.values()) if phrase_counts else 0
    top_repeated_phrase = max(phrase_counts, key=phrase_counts.get) if phrase_counts else ""
    duplicate_ratio = round(max_repeat_count / max(1, len(text_list)), 3) if text_list else 0.0

    # 3. 觀音關鍵字命中
    keyword_hits = sum(1 for kw in GUANYIN_KEYWORDS if kw in full_text)

    # 4. 綜合品質評分 (0 ~ 100)
    # 基準分以中文字比例為主
    score = chinese_ratio * 70.0
    # 關鍵字命中加分 (最高 20 分)
    score += min(20.0, keyword_hits * 4.0)
    # 豐富度加分 (段落越多分數越完整，最高 10 分)
    score += min(10.0, len(segments) * 0.2)

    # 嚴格處罰項：
    # 若重複率超過 20% (跳針嚴重，如腮筒或一秒鐘)，大幅扣分
    if duplicate_ratio > 0.20 or max_repeat_count >= 6:
        penalty = min(60.0, max_repeat_count * 2.0)
        score -= penalty

    # 若是純英文歌 (中文字小於 15%)，大幅扣分
    if chinese_ratio < 0.15:
        score -= 50.0

    score = max(0.0, min(100.0, round(score, 1)))

    # 產生預覽文字 (前三段 + 後三段)
    preview = " / ".join(text_list[:3])
    if len(text_list) > 6:
        preview += " ... " + " / ".join(text_list[-2:])

    return {
        "score": score,
        "segments_count": len(segments),
        "chinese_ratio": chinese_ratio,
        "english_ratio": english_ratio,
        "duplicate_ratio": duplicate_ratio,
        "max_repeat_count": max_repeat_count,
        "top_repeated": f"{top_repeated_phrase} (x{max_repeat_count})" if max_repeat_count >= 4 else "無明顯跳針",
        "keyword_hits": keyword_hits,
        "preview": preview[:200],
    }


def arbitrate_subtitles(
    candidates: Dict[str, List[Dict[str, Any]]],
    meta: Dict[str, Any],
    manual_choice: Optional[str] = None
) -> Tuple[str, str, Dict[str, Any]]:
    """多軌字幕仲裁與選取函式：

    回傳：
      (selected_track, decision_reason, all_evaluations)
    """
    evals: Dict[str, Dict[str, Any]] = {}
    for track_name, segs in candidates.items():
        evals[track_name] = evaluate_caption_quality(segs)

    # 手動指定優先
    if manual_choice and manual_choice in candidates and candidates[manual_choice]:
        return manual_choice, f"人工手動指定採用 [{manual_choice}] 軌道", evals

    # 若有官方字幕，且官方字幕品質及格 (中文字比例正常、無跳針)，優先官方字幕
    vtt_eval = evals.get("official_vtt")
    if vtt_eval and vtt_eval["segments_count"] > 0 and vtt_eval["score"] >= 60.0:
        return "official_vtt", "官方手動字幕品質優良 (評分最高)，優先選用", evals

    # 比對 Whisper 與 OCR
    whisper_eval = evals.get("whisper", {"score": 0.0})
    ocr_eval = evals.get("ocr", {"score": 0.0})

    # 客家話 / 方言或跳針判定：Whisper 出現嚴重跳針，而 OCR 得分顯著勝出
    if ocr_eval.get("score", 0) >= 40.0 and (
        whisper_eval.get("max_repeat_count", 0) >= 6 or
        whisper_eval.get("score", 0) < ocr_eval.get("score", 0) - 20.0
    ):
        reason = (
            f"音軌轉錄偵測到方言或跳針雜訊 ({whisper_eval.get('top_repeated')}, 得分 {whisper_eval['score']})；"
            f"畫面 OCR 辨識出電視中文字幕條且評分更高 ({ocr_eval['score']} 分)，由 OCR 勝出！"
        )
        return "ocr", reason, evals

    # 純音樂 / 英文歌 BGM 判定
    if whisper_eval.get("chinese_ratio", 0) < 0.20 and whisper_eval.get("english_ratio", 0) > 0.40:
        if ocr_eval.get("score", 0) >= 40.0:
            return "ocr", "音軌為純英文歌曲 BGM，切換至畫面 OCR 取得景點中文文字", evals
        return "none", "全片為背景音樂 (BGM) 或無有效中文人聲，標記為純音樂影片 (audio_bgm_only)", evals

    # 一般情況：取評分最高者
    best_track = max(evals.keys(), key=lambda k: evals[k]["score"])
    best_score = evals[best_track]["score"]

    if best_score < 25.0:
        return "none", "所有軌道評分皆低於可用門檻，無有效逐字稿", evals

    reason = f"依多軌評分綜合仲裁，[{best_track}] 得分最高 ({best_score} 分) 勝出"
    return best_track, reason, evals


# =========================================================================
# 代表性畫面擷取 (任務 4B)
# =========================================================================

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

    # 1. 優先選取字幕中出現觀音關鍵字的時間點
    target_times: List[Tuple[float, str]] = []
    for item in timestamps:
        text = item.get("text", "")
        if any(kw in text for kw in GUANYIN_KEYWORDS):
            sec = item.get("start_seconds", 0.0)
            if 1.0 <= sec <= duration_seconds - 1.0:
                target_times.append((sec, text))

    # 2. 補充均勻時間點 (15%, 35%, 55%, 75%, 90%)
    if len(target_times) < target_count:
        for p in [0.15, 0.35, 0.55, 0.75, 0.90]:
            sec = duration_seconds * p
            if 0 < sec < duration_seconds:
                desc = "觀音區相關影片畫面"
                for item in timestamps:
                    if item.get("start_seconds", 0) <= sec <= item.get("end_seconds", 0):
                        desc = item.get("text", desc)
                        break
                target_times.append((sec, desc))

    # 避免截圖時間點過於接近 (間隔至少 3 秒)
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


# =========================================================================
# 報告生成與 Markdown 格式化
# =========================================================================

def generate_markdown(record: Dict[str, Any]) -> str:
    """產出排版美觀的影片報告 Markdown (含多軌比對表格、截圖與逐字稿)。"""
    title = record.get("title") or record.get("id")
    channel = record.get("source_name") or "未知頻道"
    url = record.get("source_url") or ""
    status = record.get("crawl_status") or "已處理"
    crawled_at = record.get("crawled_at") or ""
    audit = record.get("multi_track_audit", {})
    images = record.get("images", [])
    timestamps = record.get("timestamps", [])

    lines = [
        f"# {title}",
        "",
        "## 影片基本資訊",
        f"- **資料編號**：`{record.get('id')}`",
        f"- **頻道來源**：{channel}",
        f"- **原始網址**：[{url}]({url})",
        f"- **爬取狀態**：{status}",
        f"- **處理時間**：{crawled_at}",
        "",
        "## 🎯 多軌字幕比較與仲裁決策 (Multi-Track Caption Arbitration)",
        f"- **系統選用軌道**：`{audit.get('selected_track', 'none')}`",
        f"- **仲裁決策原因**：{audit.get('selection_reason', '無')}",
        "",
        "| 來源軌道 | 段落數 | 中文比例 | 重複跳針率 | 關鍵字命中 | 綜合品質評分 | 決策結果 |",
        "| :--- | :---: | :---: | :---: | :---: | :---: | :---: |",
    ]

    scores = audit.get("scores", {})
    details = audit.get("track_evaluations", {})
    selected = audit.get("selected_track")

    track_names = {
        "official_vtt": "軌道 A：官方/自動字幕 (.vtt)",
        "whisper": "軌道 B：音軌語音辨識 (Whisper)",
        "ocr": "軌道 C：畫面硬字幕 (OpenCV + OCR)"
    }

    for track_key, track_label in track_names.items():
        dt = details.get(track_key, {})
        sc = scores.get(track_key, 0.0)
        is_sel = "⭐ **[選用]**" if track_key == selected else "備選 / 捨棄"
        if dt.get("segments_count", 0) == 0:
            lines.append(f"| {track_label} | 0 | 0.0% | 0.0% | 0 | 0.0 | 未取得 |")
        else:
            lines.append(
                f"| {track_label} | {dt.get('segments_count')} | "
                f"{int(dt.get('chinese_ratio', 0)*100)}% | "
                f"{int(dt.get('duplicate_ratio', 0)*100)}% ({dt.get('top_repeated')}) | "
                f"{dt.get('keyword_hits')} | **{sc}** | {is_sel} |"
            )

    lines.append("")
    lines.append("> 💡 **人工審核指示**：如需強制覆寫為其他版本，請在單片 JSON 中設定 `\"manual_override\": \"track_name\"` 重新產生即可。")
    lines.append("")

    lines.append("## 代表性畫面截圖 (任務 4B)")
    if images:
        for img in images:
            img_md_path = f"../{img['path']}"
            lines.append(f"### 畫面 [{img['timestamp']}] - {img['description']}")
            lines.append(f"![{img['description']}]({img_md_path})\n")
    else:
        lines.append("*（未擷取畫面或無影像串流）*\n")

    lines.append("## 逐字稿內容 (選用版本)")
    if timestamps:
        for item in timestamps:
            time_tag = item.get("start", format_seconds(item.get("start_seconds", 0)))
            lines.append(f"- `[{time_tag}]` {item.get('text', '')}")
    else:
        lines.append("*（此影片無可用之字幕逐字稿內容）*")

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


# =========================================================================
# 主處理流程 (相容 main.py 呼叫)
# =========================================================================

def process_video(
    entry: Dict[str, Any],
    out_dir: str | Path = "output",
    whisper_model: str = "base",
    enable_ocr: bool = True
) -> Dict[str, Any]:
    """核心串接函式：執行 YouTube 影片下載、多軌字幕擷取、品質仲裁與畫面選取。

    符合組員 1 main.py 規範與組員 4 index.jsonl 規範。
    """
    ensure_runtime_dependencies()
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

    if item_id in ("manual_001", "video_unknown"):
        item_id = f"video_{vid}"

    work_dir = out.parent / "downloads" / vid if out.name == "output" else out / "downloads" / vid
    videos_dir = out / "videos"
    images_dir = out / "images"
    videos_dir.mkdir(parents=True, exist_ok=True)
    images_dir.mkdir(parents=True, exist_ok=True)

    status_code = "200"
    status_label = "success"

    try:
        # 1. 下載中繼資料與字幕
        print(f"\n[組員3影片模組] 🎬 開始處理 {item_id}: {url}")
        download_video_and_metadata(url, work_dir)

        # 讀取中繼資料
        info_files = list(work_dir.glob("*.info.json"))
        meta: Dict[str, Any] = {}
        if info_files:
            meta = json.loads(info_files[0].read_text(encoding="utf-8", errors="replace"))

        title = meta.get("title") or entry.get("title_hint") or f"YouTube 影片 {vid}"
        channel = meta.get("channel") or meta.get("uploader") or (urlparse(url).hostname or "YouTube")

        # 尋找下載的影音檔
        media_files = sorted(work_dir.glob("*.mp4")) + sorted(work_dir.glob("*.mkv")) + sorted(work_dir.glob("*.webm"))
        media_path = media_files[0] if media_files else None

        # 尋找專用音訊檔 (若 yt-dlp 分離下載，優先使用專用音訊串流 m4a/opus/mp3)
        audio_files = sorted(work_dir.glob("*.m4a")) + sorted(work_dir.glob("*.mp3")) + sorted(work_dir.glob("*.wav")) + sorted(work_dir.glob("*.aac")) + sorted(work_dir.glob("*.opus"))
        audio_path = audio_files[0] if audio_files else media_path

        # 2. 多軌並行擷取 (Multi-Track)
        candidates: Dict[str, List[Dict[str, Any]]] = {
            "official_vtt": [],
            "whisper": [],
            "ocr": [],
        }

        # 軌道 A: 官方/自動字幕 (.vtt)
        vtt_files = sorted(work_dir.glob("*.vtt"))
        if vtt_files:
            preferred = next((f for f in vtt_files if any(k in f.name.lower() for k in ["zh-hant", "zh-tw", "zh"])), vtt_files[0])
            candidates["official_vtt"] = parse_vtt(preferred)
            print(f"  -> [軌道 A] 解析線上字幕: {preferred.name} ({len(candidates['official_vtt'])} 段)")

        # 軌道 B: 音軌語音辨識 (Whisper)
        target_audio = audio_path or media_path
        if target_audio and target_audio.is_file():
            print(f"  -> [軌道 B] 啟動 Whisper ({whisper_model}) 音軌轉錄: {target_audio.name} (啟用防跳針與純音樂過濾)...")
            try:
                candidates["whisper"] = whisper_transcribe(target_audio, model_name=whisper_model)
                print(f"     ✅ Whisper 完成 ({len(candidates['whisper'])} 段)")
            except Exception as w_exc:
                print(f"     ⚠️ Whisper 轉錄未完成: {w_exc}")

        # 軌道 C: 畫面底部 OCR (當有畫面時執行，專解客家話/跳針)
        # 若是客家話相關 (標題有客家、或 Whisper 疑似跳針)，優先確保 OCR
        is_hakka_or_complex = "客家" in title or "客" in title or any(kw in title for kw in ["EP", "節目", "喫桃"])
        if enable_ocr and media_path and media_path.is_file():
            print("  -> [軌道 C] 啟動畫面底部硬字幕 OCR 辨識 (抽格採樣)...")
            try:
                candidates["ocr"] = ocr_burned_in_subtitles(media_path, sample_seconds=2.0)
                print(f"     ✅ OCR 辨識完成 ({len(candidates['ocr'])} 段)")
            except Exception as ocr_exc:
                print(f"     ⚠️ OCR 辨識未執行: {ocr_exc}")

        # 3. 智慧品質評分與仲裁 (Arbitration)
        print("  -> [決策引擎] 進行多軌品質評分與版本仲裁...")
        selected_track, decision_reason, track_evals = arbitrate_subtitles(
            candidates=candidates,
            meta=meta,
            manual_choice=entry.get("manual_override")
        )
        print(f"     🏆 仲裁結果: 由 [{selected_track}] 勝出！原因: {decision_reason}")

        # 依勝出版本選取最終 timestamps
        final_timestamps = candidates.get(selected_track, [])
        if not final_timestamps and selected_track == "none":
            # 若全無有效中文，以最長者作為備用或留空
            final_timestamps = []

        # 4. 代表性畫面智慧擷取 (任務 4B)
        saved_images: List[Dict[str, Any]] = []
        if media_path and media_path.is_file():
            saved_images = extract_representative_frames(
                video_path=media_path,
                output_dir=images_dir,
                item_id=item_id,
                timestamps=final_timestamps or candidates.get("whisper", []),
                target_count=4
            )
            print(f"  -> 已選取並儲存 {len(saved_images)} 張代表性畫面至 output/images/")

        # 5. 整合清洗後全文
        full_content = "\n\n".join(
            re.sub(r"\s+", " ", seg["text"]).strip()
            for seg in final_timestamps
        ) if final_timestamps else "（此影片無可用之繁體中文逐字稿紀錄）"

        status_str = f"success ({selected_track})" if final_timestamps else "success (no_usable_subtitles)"

        # 6. 組員 4 共享資料結構 (index.jsonl 規格)
        knowledge_record = {
            "id": item_id,
            "type": "video",
            "title": title,
            "source_url": url,
            "source_name": channel,
            "content": full_content,
            "images": saved_images,
            "links": [url],
            "timestamps": final_timestamps,
            "crawl_status": status_str,
            "crawled_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            "multi_track_audit": {
                "selected_track": selected_track,
                "selection_reason": decision_reason,
                "scores": {k: v.get("score", 0.0) for k, v in track_evals.items()},
                "track_evaluations": track_evals,
            },
            "metadata": {
                "video_id": vid,
                "duration": meta.get("duration"),
                "view_count": meta.get("view_count"),
                "upload_date": meta.get("upload_date"),
            }
        }

        # 7. 寫出成果
        json_path = videos_dir / f"{item_id}.json"
        md_path = videos_dir / f"{item_id}.md"

        json_path.write_text(json.dumps(knowledge_record, ensure_ascii=False, indent=2), encoding="utf-8")
        md_content = generate_markdown(knowledge_record)
        md_path.write_text(md_content, encoding="utf-8")

        update_index_jsonl(out / "index.jsonl", knowledge_record)

        elapsed = round((time.monotonic() - start_monotonic) * 1000)
        print(f"  [完成] {item_id} 多軌處理成功！耗時 {elapsed} ms")

        return {
            "status": status_label,
            "reason": decision_reason,
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
        print(f"  [錯誤] 處理影片失敗: {err_msg}")

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
    parser = argparse.ArgumentParser(
        description="YouTube 多軌字幕逐字稿仲裁與代表畫面擷取模組 (觀音區知識庫 - 組員 3)"
    )
    parser.add_argument("--url", help="單一 YouTube 影片網址 (方便現場抽測)")
    parser.add_argument("--id", help="指定資料代號 ID (搭配 --url 使用，如 extra_042)")
    parser.add_argument("--urls", default="urls.csv", help="網址清單 CSV 檔案路徑 (預設 urls.csv)")
    parser.add_argument("--out-dir", default="output", help="輸出資料夾路徑 (預設 output)")
    parser.add_argument("--whisper-model", default="base", help="Whisper 辨識模型大小 (預設 base)")
    parser.add_argument("--no-ocr", action="store_true", help="關閉畫面 OCR 辨識 (加快處理速度)")
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
        print(f"[組員3] 執行單一網址多軌處理: {args.url}")
        res = process_video(
            entry,
            out_dir=out_path,
            whisper_model=args.whisper_model,
            enable_ocr=not args.no_ocr
        )
        print(f"[處理結果] 狀態: {res['status']}, 決策: {res['reason']}, 耗時: {res['elapsed_ms']}ms")
        return 0 if res["status"] == "success" else 1

    # 2. 批次處理 urls.csv 中的 video 項目
    urls_file = Path(args.urls)
    if not urls_file.is_file():
        print(f"[錯誤] 找不到網址檔案: {urls_file}", file=sys.stderr)
        return 1

    with open(urls_file, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        video_entries = [r for r in reader if r.get("type") == "video"]

    if args.id:
        video_entries = [r for r in video_entries if r.get("id") == args.id]

    print(f"[組員3] 找到 {len(video_entries)} 筆待處理影片，開始執行多軌字幕仲裁管線...")
    success_count = 0

    for idx, e in enumerate(video_entries, 1):
        print(f"\n[{idx}/{len(video_entries)}] 正在處理 {e.get('id')}: {e.get('url')}")
        res = process_video(
            e,
            out_dir=out_path,
            whisper_model=args.whisper_model,
            enable_ocr=not args.no_ocr
        )
        if res["status"] == "success":
            success_count += 1

    print(f"\n[處理完成] 共處理 {len(video_entries)} 筆影片，成功: {success_count} 筆。")
    print(f"  - 知識庫索引: {out_path / 'index.jsonl'}")
    print(f"  - 影片報告資料夾: {out_path / 'videos'}")
    print(f"  - 代表截圖資料夾: {out_path / 'images'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
