"""正文清理與文章圖片擷取。

這個模組刻意採保守策略：只在推定的文章容器內找圖片，不把整個 ``body``
的圖片全部下載。這可避免 logo、推薦輪播與廣告圖片混進知識庫。下載器可由
呼叫端注入，方便單元測試及日後接 Selenium 的 rendered HTML。
"""
from __future__ import annotations

import hashlib
import html as html_lib
import json
import re
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import urljoin, urlsplit

import requests
from bs4 import BeautifulSoup, NavigableString, Tag

try:
    from PIL import Image
except ImportError:  # pragma: no cover - installation problem, reported by caller
    Image = None


NOISE_TAGS = ("script", "style", "noscript", "template", "nav", "header", "footer",
              "aside", "form", "iframe", "dialog")
NOISE_RE = re.compile(
    r"(?:^|[-_ ])(?:ad|ads|advert|banner|promo|promotion|share|social|cookie|popup|modal|"
    r"recommend(?:ed|ation)?|related|popular|sponsor|breadcrumb|newsletter|subscribe)"
    r"(?:$|[-_ ])",
    re.I,
)
CAROUSEL_RE = re.compile(r"(?:swiper(?:[-_ ]slide)?|carousel(?:[-_ ](?:item|wrapper))?)", re.I)
CAROUSEL_NOISE_RE = re.compile(r"(?:recommend|related|popular|sponsor|advert|promo|ad[-_ ])", re.I)
PARENT_IMAGE_NOISE_RE = re.compile(
    r"(?:^|[-_ ])(?:ad|ads|advert|banner|promo|promotion|share|social|cookie|popup|modal|"
    r"recommend(?:ed|ation)?|related|popular|sponsor|tracker|button)(?:$|[-_ ])", re.I)
BAD_IMAGE_RE = re.compile(
    r"(?:logo|icon|favicon|avatar|banner|advert|adserver|doubleclick|pixel|tracker|"
    r"beacon|share|social|button|facebook|instagram|line(?:[-_.]|$)|loading|spinner|"
    r"placeholder|sprite)", re.I,
)
BAD_HOST_RE = re.compile(r"(?:doubleclick|googlesyndication|facebook\.com|facebook\.net|"
                         r"google-analytics|adnxs|googletagmanager)", re.I)
CHALLENGE_RE = re.compile(r"(?:just a moment|cloudflare|attention required|access denied|"
                           r"verify you are human|privacy error|enable javascript)", re.I)
ATTR_PRIORITY = ("data-src", "data-original", "data-lazy-src", "data-url", "srcset", "src")


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", html_lib.unescape(value or "")).strip()


def _node_noise(node: Tag) -> bool:
    attrs = node.attrs or {}
    classes = attrs.get("class", [])
    if isinstance(classes, str):
        classes = [classes]
    values = " ".join([node.name or "", str(attrs.get("id", "")), " ".join(classes)])
    if NOISE_RE.search(values):
        return True
    if CAROUSEL_RE.search(values):
        # Keep a primary photo gallery. Remove only carousels nested in a
        # recommendation/advertising section.
        for ancestor in node.parents:
            aattrs = ancestor.attrs or {}
            aclasses = aattrs.get("class", [])
            if isinstance(aclasses, str):
                aclasses = [aclasses]
            av = " ".join([ancestor.name or "", str(aattrs.get("id", "")), " ".join(aclasses)])
            if CAROUSEL_NOISE_RE.search(av):
                return True
    return False


def _is_challenge(soup: BeautifulSoup) -> bool:
    title = _clean_text(soup.title.get_text(" ") if soup.title else "")
    sample = _clean_text(soup.get_text(" ", strip=True))[:3000]
    return bool(CHALLENGE_RE.search(title) or (len(sample) < 180 and CHALLENGE_RE.search(sample)))


def _select_root(soup: BeautifulSoup) -> Tag | None:
    candidates = []
    short_candidates = []
    selectors = (
        "article", "main", "[role='main']", "#article", "#article-content", "#main-content",
        ".article-content", ".article-body", ".post-content", ".entry-content", ".post-body",
        ".content-body", ".story-content", ".articleBody", ".article_body", ".content",
        ".maincontent", ".mainContent", ".main-content", ".article-main", ".contentBlock",
        ".profile_content", ".maincolumn", ".detail", "#pagecontents1", "#divcontent",
        ".ct", ".material_detail_01", ".fr-view", "#main-container",
    )
    for selector in selectors:
        for node in soup.select(selector):
            if not isinstance(node, Tag) or _node_noise(node):
                continue
            text_len = len(_clean_text(node.get_text(" ", strip=True)))
            # Empty article/main placeholders are common on JS sites. Prefer a
            # container with real text; retain a smaller fallback only when it has
            # at least 20 characters and a paragraph/heading.
            if text_len >= 40:
                candidates.append((text_len, node))
            elif text_len >= 20 and node.find(["p", "h1", "h2", "h3"]):
                short_candidates.append((text_len, node))
    if not candidates:
        candidates = short_candidates
    if not candidates:
        return None
    # Prefer the complete content container over a tiny nested paragraph block.
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]


def _remove_noise(root: Tag) -> None:
    for node in list(root.find_all(True)):
        if not node.attrs:
            continue  # parent was decomposed earlier in this pass
        # Some government/CMS pages place the whole article inside a form for
        # legacy routing. Keep substantive forms; remove only small/search forms.
        substantive_form = node.name == "form" and len(_clean_text(node.get_text(" ", strip=True))) >= 200
        if (node.name in NOISE_TAGS and not substantive_form) or _node_noise(node):
            node.decompose()


def _srcset(value: str) -> str:
    entries = []
    # Do not split every comma: Wikimedia and signed CDN URLs can contain
    # commas in the path/query. Candidate separators normally have whitespace.
    parts = re.split(r",\s+(?=(?:https?:)?//|/|[A-Za-z0-9_.-]+\s)", value or "")
    for part in parts:
        bits = part.strip().split()
        if bits:
            width = 0
            if len(bits) > 1:
                m = re.match(r"(\d+)(?:w|x)?", bits[1])
                width = int(m.group(1)) if m else 0
            entries.append((width, bits[0]))
    if entries:
        return max(entries)[1]
    return (value or "").strip().split()[0] if (value or "").strip() else ""


def image_candidates(img: Tag, base_url: str) -> list[str]:
    result = []
    for attr in ATTR_PRIORITY:
        value = img.get(attr)
        if not value:
            continue
        values = []
        if attr == "srcset":
            # Try the largest candidate first, then fall back to smaller/src
            # when a CDN rejects a high-resolution variant.
            parts = re.split(r",\s+(?=(?:https?:)?//|/|[A-Za-z0-9_.-]+\s)", str(value))
            ranked = []
            for part in parts:
                bits = part.strip().split()
                if not bits:
                    continue
                rank = 0
                if len(bits) > 1:
                    m = re.match(r"(\d+)(?:w|x)?", bits[1])
                    rank = int(m.group(1)) if m else 0
                ranked.append((rank, bits[0]))
            values = [u for _, u in sorted(ranked, reverse=True)]
        else:
            values = [str(value).strip()]
        for candidate in values:
            if candidate and not candidate.startswith(("data:", "blob:", "javascript:")):
                absolute = urljoin(base_url, candidate)
                if absolute not in result:
                    result.append(absolute)
    return result


def image_url(img: Tag, base_url: str) -> str:
    candidates = image_candidates(img, base_url)
    return candidates[0] if candidates else ""


def _image_allowed(src: str, img: Tag, parent_text: str) -> bool:
    attrs = " ".join([src, img.get("alt", ""), " ".join(img.get("class", []))])
    if not src or BAD_IMAGE_RE.search(attrs) or BAD_HOST_RE.search(src) or PARENT_IMAGE_NOISE_RE.search(parent_text):
        return False
    suffix = Path(urlsplit(src).path).suffix.lower()
    return suffix not in {".svg", ".gif", ".ico"}


def image_url_legacy(img: Tag, base_url: str) -> str:
    """Backward-compatible alias kept for notebooks importing the old helper."""
    for attr in ATTR_PRIORITY:
        value = img.get(attr)
        if not value:
            continue
        if attr == "srcset":
            value = _srcset(value)
        value = str(value).strip()
        if value and not value.startswith(("data:", "blob:", "javascript:")):
            return urljoin(base_url, value)
    return ""


def _caption(img: Tag) -> str:
    figure = img.find_parent("figure")
    if figure:
        cap = figure.find("figcaption")
        if cap and _clean_text(cap.get_text(" ", strip=True)):
            return _clean_text(cap.get_text(" ", strip=True))
    return _clean_text(img.get("alt") or img.get("title") or "")


def _context(img: Tag) -> str:
    p = img.find_parent(["p", "li", "figcaption"])
    if p:
        text = _clean_text(p.get_text(" ", strip=True))
        if text:
            return text[:300]
    previous = img.find_previous(["p", "li"])
    return _clean_text(previous.get_text(" ", strip=True))[:300] if previous else ""


def _download(url: str, downloader: Callable[[str], bytes] | None,
              headers: dict | None = None) -> bytes:
    if downloader:
        return downloader(url)
    request_headers = {
        "User-Agent": "GuanyinKnowledgeCrawler/1.0 (university coursework)",
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    }
    if headers:
        request_headers.update(headers)
    response = requests.get(url, timeout=15, headers=request_headers)
    response.raise_for_status()
    return response.content


def _store_image(data: bytes, destination: Path) -> tuple[int, int, str]:
    if Image is None:
        raise RuntimeError("Pillow 未安裝，無法檢查圖片尺寸")
    from io import BytesIO
    with warnings.catch_warnings():
        # Very large remote images are not useful for this assignment and can
        # consume excessive memory before the normal dimension filter runs.
        warnings.simplefilter("error", getattr(Image, "DecompressionBombWarning", UserWarning))
        with Image.open(BytesIO(data)) as source:
            width, height = source.size
            if width * height > 50_000_000:
                raise ValueError(f"像素數過大 {width}x{height}")
            if width < 150 or height < 150:
                raise ValueError(f"尺寸過小 {width}x{height}")
            ratio = max(width / height, height / width)
            if ratio > 5:
                raise ValueError(f"長寬比過大 {width}x{height}")
            rgb = source.convert("RGB")
            rgb.save(destination, format="JPEG", quality=92, optimize=True)
            return width, height, hashlib.md5(data).hexdigest()


def _markdown(node: Tag | NavigableString, image_map: dict[int, dict]) -> str:
    if isinstance(node, NavigableString):
        return _clean_text(str(node))
    if not isinstance(node, Tag):
        return ""
    if node.name in {"img"}:
        item = image_map.get(id(node))
        if not item:
            return ""
        return f"![{item['caption']}]({item['markdown_file']})"
    if node.name in {"br"}:
        return "\n"
    if node.name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
        body = _inline(node, image_map)
        return f"{'#' * int(node.name[1])} {body}\n\n" if body else ""
    if node.name in {"p", "figcaption"}:
        body = _inline(node, image_map)
        return f"{body}\n\n" if body else ""
    if node.name in {"ul", "ol"}:
        lines = []
        for li in node.find_all("li", recursive=False):
            body = _inline(li, image_map)
            if body:
                lines.append(f"- {body}")
        return "\n".join(lines) + "\n\n" if lines else ""
    if node.name == "table":
        rows = []
        for tr in node.find_all("tr"):
            cells = [_clean_text(c.get_text(" ", strip=True)) for c in tr.find_all(["th", "td"], recursive=False)]
            if cells:
                rows.append("| " + " | ".join(cells) + " |")
        if rows and not any("---" in row for row in rows[1:]):
            n = rows[0].count("|") - 1
            rows.insert(1, "| " + " | ".join(["---"] * max(1, n)) + " |")
        return "\n".join(rows) + "\n\n" if rows else ""
    return "".join(_markdown(child, image_map) for child in node.children)


def _inline(node: Tag, image_map: dict[int, dict]) -> str:
    parts = []
    for child in node.children:
        if isinstance(child, NavigableString):
            parts.append(_clean_text(str(child)))
        elif isinstance(child, Tag):
            if child.name == "img":
                parts.append(_markdown(child, image_map))
            elif child.name in {"strong", "b"}:
                text = _inline(child, image_map)
                if text: parts.append(f"**{text}**")
            elif child.name in {"em", "i"}:
                text = _inline(child, image_map)
                if text: parts.append(f"*{text}*")
            elif child.name == "a":
                text = _inline(child, image_map)
                href = child.get("href", "")
                parts.append(f"[{text}]({href})" if text and href else text)
            else:
                parts.append(_inline(child, image_map))
    return re.sub(r"[ \t]+", " ", "".join(parts)).strip()


def parse_article(html: str, page_url: str, page_id: str, image_dir: str | Path,
                  downloader: Callable[[str], bytes] | None = None,
                  image_headers: dict | None = None,
                  crawled_at: str | None = None) -> dict:
    """解析一頁 HTML，回傳可直接寫入 ``output/articles`` 的 JSON dict。"""
    soup = BeautifulSoup(html or "", "html.parser")
    title = _clean_text(soup.find("h1").get_text(" ", strip=True) if soup.find("h1")
                        else (soup.title.get_text(" ", strip=True) if soup.title else ""))
    site_meta = soup.find("meta", property="og:site_name")
    source_name = (_clean_text(site_meta.get("content", "") if site_meta else "")
                   or (urlsplit(page_url).hostname or ""))
    result = {
        # Repo schema uses ``web`` (the assignment's human-readable label is webpage).
        "id": page_id, "type": "web", "title": title, "source_url": page_url,
        "source_name": source_name, "author": "", "published_at": "", "content": "",
        "images": [], "links": [], "content_status": "missing", "processing_status": "partial",
        "processing_reason": "", "crawled_at": crawled_at or datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
    }
    for key, aliases in (("author", ("author", "byline")), ("published_at", ("date", "pubdate", "article:published_time"))):
        for alias in aliases:
            tag = soup.find("meta", attrs={"name": alias})
            if tag is None:
                tag = soup.find("meta", attrs={"property": alias})
            if tag and tag.get("content"):
                result[key] = _clean_text(tag["content"]); break
    # JSON-LD is common on news/blog pages and is metadata only. Its image
    # field is intentionally not downloaded because it may be a site-wide thumbnail.
    for script in soup.select("script[type='application/ld+json']"):
        try:
            payload = json.loads(script.string or script.get_text())
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        objects = payload if isinstance(payload, list) else [payload]
        for obj in objects:
            if not isinstance(obj, dict):
                continue
            if not result["title"] and obj.get("headline"):
                result["title"] = _clean_text(str(obj["headline"]))
            author = obj.get("author")
            if not result["author"] and author:
                if isinstance(author, dict):
                    author = author.get("name", "")
                elif isinstance(author, list):
                    author = ", ".join(str(x.get("name", x)) if isinstance(x, dict) else str(x) for x in author)
                result["author"] = _clean_text(str(author))
            if not result["published_at"] and obj.get("datePublished"):
                result["published_at"] = _clean_text(str(obj["datePublished"]))
    if _is_challenge(soup):
        result["processing_reason"] = "頁面疑似 Cloudflare／隱私／人機驗證頁，未將其當作正文"
        result["processing_status"] = "blocked"
        return result
    root = _select_root(soup)
    if root is None:
        result["processing_reason"] = "找不到可信的文章容器；可能需要瀏覽器渲染或人工檢查"
        result["processing_status"] = "needs_review"
        return result
    _remove_noise(root)
    image_dir = Path(image_dir); image_dir.mkdir(parents=True, exist_ok=True)
    image_map: dict[int, dict] = {}; seen_hashes: set[str] = set(); failures = []
    for img in root.find_all("img"):
        src = image_url(img, page_url)
        attrs = " ".join([src, img.get("alt", ""), " ".join(img.get("class", []))])
        parent_text = " ".join(str(x) for x in img.parent.get("class", []) if img.parent) if img.parent else ""
        if not src or BAD_IMAGE_RE.search(attrs) or BAD_HOST_RE.search(src) or PARENT_IMAGE_NOISE_RE.search(parent_text):
            continue
        suffix = Path(urlsplit(src).path).suffix.lower()
        if suffix in {".svg", ".gif", ".ico"}:
            continue
        try:
            data = _download(src, downloader, image_headers)
            digest = hashlib.md5(data).hexdigest()
            if digest in seen_hashes:
                continue
            filename = f"{page_id}_image_{len(result['images']) + 1:02d}.jpg"
            destination = image_dir / filename
            width, height, digest = _store_image(data, destination)
            seen_hashes.add(digest)
        except Exception as exc:
            failures.append(str(exc)); continue
        item = {"file": f"images/{filename}", "file_path": f"output/images/{filename}",
                "source_url": src, "caption": _caption(img), "context_paragraph": _context(img),
                "article_id": page_id, "kind": "article_image", "width": width, "height": height,
                "md5": digest, "markdown_file": f"../images/{filename}"}
        result["images"].append(item); image_map[id(img)] = item
    markdown = _markdown(root, image_map).strip()
    markdown = re.sub(r"\n{3,}", "\n\n", markdown)
    result["content"] = markdown
    links = []
    for anchor in root.select("a[href]"):
        href = urljoin(page_url, anchor.get("href", "")).split("#", 1)[0]
        if href.startswith(("http://", "https://")) and href not in links:
            links.append(href)
    result["links"] = links[:300]
    if len(re.sub(r"\s+", "", markdown)) >= 40:
        result["content_status"] = "ok"
        result["processing_status"] = "complete"
    else:
        result["processing_reason"] = "正文太短或為動態空殼，需人工檢查／提供 rendered HTML"
        result["processing_status"] = "needs_review"
    if not result["images"]:
        result["processing_reason"] = (result["processing_reason"] + "; " if result["processing_reason"] else "") + "無可取得或適合保留的圖片"
    return result


def write_article_outputs(result: dict, output_dir: str | Path) -> tuple[Path, Path]:
    """寫入 JSON 與 Markdown；回傳兩個檔案路徑。"""
    output_dir = Path(output_dir); folder = output_dir / "articles"; folder.mkdir(parents=True, exist_ok=True)
    data = dict(result)
    for item in data.get("images", []):
        item.pop("markdown_file", None)
    json_path = folder / f"{result['id']}.json"
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    front = ["---", f"title: {result.get('title', '')}", f"author: {result.get('author', '')}",
             f"published_at: {result.get('published_at', '')}", f"source_url: {result.get('source_url', '')}", "---", ""]
    md_path = folder / f"{result['id']}.md"
    md_path.write_text("\n".join(front) + result.get("content", "") + "\n", encoding="utf-8")
    return json_path, md_path

