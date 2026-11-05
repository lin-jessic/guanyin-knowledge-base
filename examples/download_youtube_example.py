"""YouTube 影片下載範例程式 (使用 yt-dlp Python API)
桃園市觀音區地方知識庫專案 - 組員 3 實作範例

本範例展示 3 種常見下載情境：
1. 情境一：標準下載（MP4 影片 + 官方/自動字幕 + 中繼資料 JSON）[推薦專案使用]
2. 情境二：極簡下載（僅下載 MP4 影片檔，指定最高 1080p）
3. 情境三：僅下載音訊 (M4A/MP3，供 Whisper 語音轉錄使用，極省流量)

執行方式：
  python examples/download_youtube_example.py
"""

from pathlib import Path
import json
import yt_dlp

# 自動取得 imageio-ffmpeg 提供的 ffmpeg 執行檔路徑 (避免 Windows 系統未安裝 ffmpeg 報錯)
try:
    import imageio_ffmpeg
    FFMPEG_PATH = imageio_ffmpeg.get_ffmpeg_exe()
except ImportError:
    FFMPEG_PATH = None


# =====================================================================
# 範例一：專案標準下載 (下載 MP4 + 字幕 .vtt + 影片資訊 JSON)
# =====================================================================
def download_video_full(url: str, output_dir: str = "output/demo_videos") -> dict:
    """下載影片、字幕與中繼資料 (組員 3 任務 4A/4B 所需規格)

    :param url: YouTube 影片網址 (例: https://youtu.be/2hbu5n9VLZY)
    :param output_dir: 下載檔案存放目錄
    :return: 影片詳細資訊字典 (包含標題、時長、觀看次數等)
    """
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    # 輸出檔名格式: output_dir/影片ID/影片ID.副檔名
    out_template = str(out_path / "%(id)s" / "%(id)s.%(ext)s")

    ydl_opts = {
        # 1. 輸出檔案路徑模板
        "outtmpl": out_template,

        # 2. 格式選擇：優先選擇 MP4 容器，畫質最高 1080p，兼顧下載速度與畫質
        "format": "bestvideo[ext=mp4][height<=1080]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "merge_output_format": "mp4",

        # 3. 字幕設定 (任務 4A)
        "writesubtitles": True,       # 下載上傳者官方字幕
        "writeautomaticsub": True,    # 若無官方字幕，下載 YouTube 自動生成字幕
        "subtitleslangs": ["zh-Hant", "zh-TW", "zh", "zh-Hans", "en"], # 優先繁中
        "subtitlesformat": "vtt",     # 字幕存為 .vtt 格式

        # 4. 中繼資料設定
        "writeinfojson": True,        # 將標題、頻道、發布日期存成 .info.json

        # 5. 反爬與客戶端模擬 (避開 YouTube SABR 與 The page needs to be reloaded 錯誤)
        "extractor_args": {
            "youtube": {
                "player_client": ["android", "ios"]
            }
        },

        # 6. 其他控制
        "noplaylist": True,           # 若傳入播放清單網址，僅下載單支影片
        "quiet": False,               # 顯示下載進度條
        "no_warnings": False,
    }

    # 若系統已安裝 imageio-ffmpeg，指定其路徑
    if FFMPEG_PATH:
        ydl_opts["ffmpeg_location"] = FFMPEG_PATH

    print(f"\n[開始下載] 網址: {url}")
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        # extract_info 會執行下載，並回傳影片的詳細中繼資料 dict
        info = ydl.extract_info(url, download=True)

    print("\n[下載完成！]")
    print(f"  - 影片標題: {info.get('title')}")
    print(f"  - 影片頻道: {info.get('uploader')}")
    print(f"  - 影片長度: {info.get('duration')} 秒")
    print(f"  - 儲存位置: {out_path / info['id']}")
    return info


# =====================================================================
# 範例二：極簡下載 (僅下載單一 MP4 影片)
# =====================================================================
def download_simple_mp4(url: str, output_dir: str = "output/demo_simple") -> str:
    """最簡單的單片 MP4 下載範例"""
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    ydl_opts = {
        "outtmpl": str(out_path / "%(title)s.%(ext)s"),
        "format": "best[ext=mp4]/best",
        "noplaylist": True,
    }
    if FFMPEG_PATH:
        ydl_opts["ffmpeg_location"] = FFMPEG_PATH

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        filename = ydl.prepare_filename(info)

    print(f"[極簡下載完成] 檔案位置: {filename}")
    return filename


# =====================================================================
# 範例三：僅下載音訊 (音軌轉 M4A，Whisper 轉錄專用)
# =====================================================================
def download_audio_only(url: str, output_dir: str = "output/demo_audio") -> str:
    """只下載音軌，檔案極小（約 5~10MB），適合直接餵給 Whisper 語音轉錄"""
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    ydl_opts = {
        "outtmpl": str(out_path / "%(id)s.%(ext)s"),
        "format": "bestaudio[ext=m4a]/bestaudio/best",
        "noplaylist": True,
    }
    if FFMPEG_PATH:
        ydl_opts["ffmpeg_location"] = FFMPEG_PATH

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        filename = ydl.prepare_filename(info)

    print(f"[音軌下載完成] 檔案位置: {filename}")
    return filename


if __name__ == "__main__":
    # 測試網址：觀音區相關測試影片 (老師清單中的 page_026 影片)
    TEST_URL = "https://youtu.be/2hbu5n9VLZY"

    print("=" * 60)
    print("YouTube 下載範例展示 (使用專案環境已安裝之 yt-dlp)")
    print(f"FFmpeg 支援狀態: {'已啟用 (' + FFMPEG_PATH + ')' if FFMPEG_PATH else '未找到'}")
    print("=" * 60)

    # 示範執行範例一（專案完整下載）
    # 如需測試，可直接執行此程式
    print("\n提示：如需在終端機直接測試下載，可執行：")
    print("  python -m yt_dlp -f \"best[ext=mp4]\" --write-sub --write-auto-sub \"https://youtu.be/2hbu5n9VLZY\"")
    print("\n或直接在 Python 中呼叫 download_video_full(url)")
