"""Photo catalogue built from the team's existing article/film JSON outputs.
Never changes their files and never treats crawl success as copyright permission.
"""
from __future__ import annotations
import hashlib
import html
import json
import re
from pathlib import Path
from functools import lru_cache
from . import store

ROOT = store.ROOT
EXTS = {'.jpg', '.jpeg', '.png', '.webp', '.gif'}


def normalize_path(value):
    raw = str(value or '').replace('\\', '/').strip()
    if raw.startswith('output/'):
        raw = raw[7:]
    if raw.startswith('../images/'):
        raw = raw[3:]
    p = Path(raw)
    if p.is_absolute() or '..' in p.parts or not raw.startswith('images/') or p.suffix.lower() not in EXTS:
        return None
    target = (ROOT / 'output' / p).resolve()
    if not target.is_relative_to((ROOT / 'output' / 'images').resolve()):
        return None
    return raw if target.is_file() else None


def tidy(value, limit=150):
    s = html.unescape(str(value or ''))
    s = re.sub(r'!\[[^\]]*\]\([^\n)]*\)', ' ', s)
    s = re.sub(r'\[([^\]]+)\]\([^\n)]*\)', r'\1', s)
    s = re.sub(r'<[^>]*>', ' ', s)
    s = re.sub(r'[`*_#|]+', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip(' -|:;，、。')
    return s[:limit]


@lru_cache(maxsize=1)
def photo_inventory():
    """Walk JSON files; report duplicates and invalid images separately."""
    from PIL import Image, UnidentifiedImageError
    store.init()
    folder = ROOT / 'output' / 'articles'
    raw = []
    for file in sorted(folder.glob('*.json')):
        try:
            article = json.loads(file.read_text(encoding='utf-8-sig'))
        except (ValueError, OSError):
            continue
        if not isinstance(article, dict):
            continue
        rid = str(article.get('id') or file.stem)
        title = tidy(article.get('title') or rid)
        url = str(article.get('source_url') or '')
        for item in article.get('images') or []:
            if not isinstance(item, dict):
                continue
            path = normalize_path(item.get('file') or item.get('file_path'))
            raw.append((rid, title, url, item, path))
    issues = {'no_file': 0, 'unreadable': 0, 'too_small': 0, 'duplicate': 0, 'no_source': 0, 'no_caption': 0}
    out = []
    hashes = set()
    with store.connect() as db:
        rights = {r['path'] for r in db.execute('SELECT path FROM media_rights WHERE allow_public=1')}
    for rid, title, url, item, path in raw:
        if not path:
            issues['no_file'] += 1
            continue
        full = ROOT / 'output' / path
        try:
            with Image.open(full) as im:
                im.verify()
            with Image.open(full) as im:
                w, h = im.size
        except (OSError, ValueError, UnidentifiedImageError):
            issues['unreadable'] += 1
            continue
        if min(w, h) < 140:
            issues['too_small'] += 1
            continue
        digest = hashlib.sha256(full.read_bytes()).hexdigest()
        if digest in hashes:
            issues['duplicate'] += 1
            continue
        hashes.add(digest)
        caption = tidy(item.get('caption'), 115)
        image_source = str(item.get('source_url') or '').strip()
        if not caption or caption.isnumeric():
            issues['no_caption'] += 1
            caption = title + '｜來源圖片'  # Descriptive label, NOT invented photographic content
        if not image_source:
            issues['no_source'] += 1
        out.append({'path': path, 'id': rid, 'title': title, 'caption': caption,
                    'article_url': url, 'image_source': image_source, 'width': w, 'height': h,
                    'approved': path in rights, 'rights': '已標記允許展示' if path in rights else '授權待核對'})
    images_on_disk = sum(1 for p in (ROOT / 'output' / 'images').glob('*') if p.is_file() and p.suffix.lower() in EXTS)
    summary = {'records': len(raw), 'valid': len(out), 'on_disk': images_on_disk,
               'orphan_files': max(0, images_on_disk - len({r[4] for r in raw if r[4]})),
               'approved': sum(x['approved'] for x in out), 'issues': issues}
    return out, summary


def gallery_listing(q='', page=1, per_page=36, approved_only=False):
    all_photos, stats = photo_inventory()
    if approved_only:
        all_photos = [x for x in all_photos if x['approved']]
    if q:
        term = q.casefold()
        all_photos = [x for x in all_photos if term in (' '.join((x['title'], x['caption'], x['id']))).casefold()]
    total = len(all_photos)
    page = max(1, min(page, max(1, (total + per_page - 1) // per_page)))
    return all_photos[(page - 1) * per_page:page * per_page], total, page, stats


def photos_for_record(record):
    """Photo set for the source detail page without pretending the license is verified."""
    try:
        entries = json.loads(record.get('image_json') or '[]')
    except ValueError:
        entries=[]
    with store.connect() as db:
        rights = {r['path'] for r in db.execute('SELECT path FROM media_rights WHERE allow_public=1')}
    out=[]
    for item in entries[:120]:
        if not isinstance(item,dict):continue
        path=normalize_path(item.get('file') or item.get('file_path'))
        if not path:continue
        out.append({'path':path, 'caption':tidy(item.get('caption')) or tidy(record.get('title'))+'｜來源圖片',
                    'rights':'已標記允許展示' if path in rights else '授權待核對',
                    'image_source':str(item.get('source_url') or '')})
    return out
