"""觀音文章與圖片展示頁（修正版）
在 guanyin-knowledge-base 專案根目錄執行：py -3.12 build_articles_page_fixed.py
使用已存在的 output/articles/*.json 和 output/images/*；不觸碰爬蟲程式。
即使 JavaScript 無法執行，文章、文字、圖片仍可顯示。
"""
from pathlib import Path
import json
import shutil
import re
import html
from urllib.parse import urlsplit

ROOT = Path.cwd()
ARTICLES = ROOT / 'output' / 'articles'
IMAGES = ROOT / 'output' / 'images'
SITE = ROOT / 'site'
ASSETS = SITE / 'assets' / 'articles'
TARGET = SITE / 'articles.html'


def esc(value):
    return html.escape(str(value if value is not None else ''), quote=True)


def external_link(url, text):
    if url and urlsplit(str(url)).scheme in ('http', 'https'):
        return f'<a href="{esc(url)}" target="_blank" rel="noopener noreferrer">{esc(text)}</a>'
    return ''


def load_records():
    if not ARTICLES.is_dir():
        raise SystemExit('找不到 output/articles 資料夾。請在專案根目錄執行，並確認已 Pull 最新 GitHub 資料。')
    records = []
    for path in sorted(ARTICLES.glob('*.json')):
        try:
            d = json.loads(path.read_text(encoding='utf-8-sig'))
            if not isinstance(d, dict):
                print(f'略過非物件：{path.name}')
                continue
            images = []
            for entry in d.get('images', []) or []:
                if not isinstance(entry, dict):
                    continue
                # 每張圖依照 JSON 的 file 欄位對應 output/images，絕不自行臆造圖片。
                filename = Path(str(entry.get('file') or '').replace('\\', '/')).name
                if not filename or filename in ('.', '..'):
                    continue
                source = IMAGES / filename
                if not source.is_file():
                    print(f'圖片不存在，略過：{source}')
                    continue
                ASSETS.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, ASSETS / filename)
                images.append({'file': 'assets/articles/' + filename,
                               'caption': entry.get('caption') or '',
                               'source_url': entry.get('source_url') or ''})
            records.append({'id': d.get('id') or path.stem,
                            'title': d.get('title') or path.stem,
                            'content': str(d.get('content') or ''),
                            'author': d.get('author') or '',
                            'published_at': d.get('published_at') or '',
                            'source_url': d.get('source_url') or '',
                            'status': d.get('processing_status') or d.get('content_status') or '未標記',
                            'reason': d.get('processing_reason') or '',
                            'images': images})
        except (OSError, ValueError, TypeError) as exc:
            print(f'跳過無法解析的檔案 {path.name}: {exc}')
    return records


def card(row):
    content = row['content']
    search = ' '.join([str(row['id']), str(row['title']), content]).casefold()
    meta = '　'.join(x for x in [
        '作者：' + esc(row['author']) if row['author'] else '',
        '發布：' + esc(row['published_at']) if row['published_at'] else '',
        external_link(row['source_url'], '查看原始網頁')
    ] if x)
    parts = [f'<article class="card" data-search="{esc(search)}">',
             f'<div class="id">{esc(row["id"])} · {esc(row["status"])}</div>',
             f'<h2>{esc(row["title"])}</h2>', f'<div class="meta">{meta}</div>']
    if content:
        parts.append(f'<details><summary>展開爬取正文（{len(content):,} 字元）</summary>'
                     f'<div class="content">{esc(content)}</div></details>')
    else:
        parts.append('<p class="notice">尚無可顯示的正文</p>')
    if row['reason']:
        parts.append(f'<p class="notice">處理說明：{esc(row["reason"])}</p>')
    if row['images']:
        parts.append(f'<h3>爬取圖片（{len(row["images"])} 張）</h3><div class="gallery">')
        for image in row['images']:
            parts.append('<figure><a href="' + esc(image['file']) + '" target="_blank" rel="noopener">'
                         '<img loading="lazy" src="' + esc(image['file']) + '" alt="' + esc(image['caption'] or row['title']) + '"></a>'
                         '<figcaption>' + esc(image['caption'] or '文章圖片') + '　' + external_link(image['source_url'], '原始圖片') + '</figcaption></figure>')
        parts.append('</div>')
    else:
        parts.append('<p class="meta">目前沒有成功儲存的文章圖片</p>')
    parts.append('</article>')
    return '\n'.join(parts)


def add_nav():
    # 僅在原有導覽標記內插入文章頁；不修改任何組員模組。
    regex = re.compile(r'(<!-- GUANYIN_VIDEO_TABS_START -->.*?<nav\b[^>]*>)(.*?)(</nav>.*?<!-- GUANYIN_VIDEO_TABS_END -->)', re.I | re.S)
    for name in ('index.html', 'videos.html', 'video_quality.html', 'video_recovery.html', 'knowledge.html'):
        path = SITE / name
        if not path.exists():
            continue
        txt = path.read_text(encoding='utf-8-sig')
        def insert(match):
            existing = match.group(2)
            if re.search(r'href\s*=\s*["\']articles\.html["\']', existing, re.I):
                return match.group(0)
            return match.group(1) + existing + '<a href="articles.html">文章與圖片</a>' + match.group(3)
        updated = regex.sub(insert, txt, count=1)
        if updated != txt:
            path.write_text(updated, encoding='utf-8')
            print('已加導覽：site/' + name)


def main():
    records = load_records()
    SITE.mkdir(parents=True, exist_ok=True)
    num_images = sum(len(r['images']) for r in records)
    print('已讀取文章 JSON：', len(records), '份；成功對應圖片：', num_images, '張')
    nav = '<nav><a href="index.html">來源管理</a><a href="articles.html" class="active">文章與圖片</a><a href="videos.html">影片成果</a><a href="video_quality.html">影音分析</a><a href="video_recovery.html">影片成果 2</a><a href="knowledge.html">知識庫</a></nav>'
    head = '''<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>觀音地方知識｜文章與圖片</title>
<style>
:root{--bg:#f8f6fa;--ink:#322c41;--purple:#66547f;--muted:#807589;--line:#e8e1ed}*{box-sizing:border-box}body{margin:0;background:var(--bg);font-family:system-ui,'Microsoft JhengHei',sans-serif;color:var(--ink)}nav{display:flex;gap:6px;flex-wrap:wrap;padding:17px max(18px,calc((100vw - 1200px)/2));background:white;border-bottom:1px solid var(--line)}nav a{color:var(--purple);padding:10px 13px;text-decoration:none;border-radius:8px}nav a.active{font-weight:700;background:#ece6f4}main{max-width:1200px;padding:45px 18px 80px;margin:auto}small{color:var(--muted)}h1{font-size:clamp(32px,4vw,43px);margin:12px 0 22px}p.lead{color:var(--muted);line-height:1.9}input{width:100%;font:inherit;padding:14px 16px;border:1px solid #d8ccdf;border-radius:12px;margin:20px 0 8px}#count{color:var(--muted);font-size:14px;margin-bottom:20px}.card{background:white;border:1px solid var(--line);padding:24px;border-radius:18px;margin-bottom:18px;overflow-wrap:anywhere}.card[hidden]{display:none}.id,.meta{font-size:13px;color:var(--muted);line-height:1.8}h2{font-size:22px;margin:9px 0}h3{font-size:16px;margin-top:22px}a{color:var(--purple)}details{margin:20px 0}summary{cursor:pointer;color:var(--purple);font-weight:650}.content{white-space:pre-wrap;line-height:1.9;background:#faf9fc;border-radius:12px;padding:16px;max-height:640px;overflow:auto;font-size:14px;margin-top:12px}.gallery{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:12px}.gallery figure{margin:0;border:1px solid var(--line);border-radius:12px;overflow:hidden}.gallery img{width:100%;height:165px;object-fit:contain;background:#faf9fc;display:block}.gallery figcaption{padding:10px;color:var(--muted);font-size:12px;line-height:1.7}.notice{color:#956026}
</style></head><body>'''
    body = f'''{nav}<main><small>GUANYIN LOCAL KNOWLEDGE BASE</small><h1>文章與圖片｜爬蟲成果</h1><p class="lead">呈現已擷取的文章正文、原始來源及已儲存圖片。內容為爬蟲成果，不表示所有敘述都已經人工查證。</p><input id="q" type="search" placeholder="搜尋文章標題、正文或來源編號" aria-label="搜尋文章"><p id="count">文章 {len(records)} 篇 · 成功對應圖片 {num_images} 張</p><section id="results">'''
    body += '\n'.join(card(record) for record in records)
    body += '''</section></main><script>
(function(){const input=document.getElementById('q'),cards=Array.from(document.querySelectorAll('#results article')),count=document.getElementById('count');
function update(){const query=input.value.trim().toLocaleLowerCase();let shown=0;for(const c of cards){const yes=c.dataset.search.includes(query);c.hidden=!yes;if(yes)shown++}count.textContent='顯示 '+shown+' / '+cards.length+' 篇文章';}
input.addEventListener('input',update);
})();
</script></body></html>'''
    TARGET.write_text(head + body, encoding='utf-8')
    add_nav()
    print('已建立：site/articles.html')
    print('請在專案根目錄執行：py -3.12 -m http.server 8000')
    print('再打開：http://localhost:8000/site/articles.html')

if __name__ == '__main__':
    main()
