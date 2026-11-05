"""Find and deduplicate YouTube video URLs in text, docx, or crawler output.

Examples:
    python youtube_link_filter.py resource.20260921.docx
    python youtube_link_filter.py urls.txt --output youtube_links.json
    python crawler.py | python youtube_link_filter.py -
    python youtube_link_filter.py "https://youtu.be/2hbu5n9VLZY"

For use from another Python module:
    from youtube_link_filter import find_youtube_video_links, read_source_text
    text = read_source_text("resource.20260921.docx")
    links = find_youtube_video_links(text)
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from urllib.parse import parse_qs, urlparse


URL_PATTERN = re.compile(
    r"(?i)(?:https?://)?(?:(?:www|m|music)\.)?"
    r"(?:youtube\.com|youtube-nocookie\.com|youtu\.be)/[^\s<>\"']+"
)
VIDEO_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{11}$")
TRAILING_PUNCTUATION = ".,;:!。，；：！？)]}〉」』"


def extract_video_id(url: str) -> str | None:
    """Return the 11-character ID for a YouTube video URL, or None."""
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


def read_docx_text(path: Path | str) -> str:
    """Extract plain text from a .docx file without external dependencies."""
    file_path = Path(path)
    try:
        with zipfile.ZipFile(file_path) as docx_zip:
            xml_content = docx_zip.read("word/document.xml")
            tree = ET.fromstring(xml_content)
            chunks: list[str] = []
            for elem in tree.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"):
                if elem.text:
                    chunks.append(elem.text)
            return " ".join(chunks)
    except Exception as exc:
        raise RuntimeError(f"無法讀取 docx 檔案 {path}: {exc}") from exc


def read_source_text(source: str) -> str:
    """Read text from stdin, a file (.docx, .txt, .csv, etc.), or raw string."""
    if source == "-":
        return sys.stdin.read()

    source_path = Path(source)
    if source_path.is_file():
        if source_path.suffix.lower() == ".docx":
            return read_docx_text(source_path)
        # Try utf-8-sig first, then utf-8, then fallback to ansi/cp950
        try:
            return source_path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            try:
                return source_path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                return source_path.read_text(encoding="cp950", errors="replace")

    # If not an existing file, treat the input string itself as content (e.g. single URL)
    return source


def find_youtube_video_links(text: str) -> list[dict[str, str]]:
    """Find supported YouTube video links, keeping the first URL per video ID."""
    results: list[dict[str, str]] = []
    seen_ids: set[str] = set()

    for match in URL_PATTERN.finditer(text):
        url = html.unescape(match.group(0)).rstrip(TRAILING_PUNCTUATION)
        video_id = extract_video_id(url)
        if video_id is None or video_id in seen_ids:
            continue

        seen_ids.add(video_id)
        if not url.lower().startswith(("http://", "https://")):
            url = "https://" + url
        results.append({"video_id": video_id, "url": url})

    return results


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Find and deduplicate YouTube video links in a text file, docx, or stdin."
    )
    parser.add_argument(
        "input",
        nargs="?",
        default="-",
        help="Input file (.docx, .txt, etc.), direct URL, or '-' for stdin.",
    )
    parser.add_argument(
        "--output",
        "-o",
        help="Optional output file (.json for JSON format, otherwise one URL per line).",
    )
    args = parser.parse_args()

    source_text = read_source_text(args.input)
    links = find_youtube_video_links(source_text)

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if output_path.suffix.lower() == ".json":
            output_text = json.dumps(links, ensure_ascii=False, indent=2) + "\n"
        else:
            output_text = "".join(f"{item['url']}\n" for item in links)
        output_path.write_text(output_text, encoding="utf-8")
        print(f"找到 {len(links)} 個不重複的 YouTube 影片連結，已寫入 {output_path}")
    else:
        for item in links:
            print(f"{item['video_id']}\t{item['url']}")
        print(f"共找到 {len(links)} 個不重複的 YouTube 影片連結", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
