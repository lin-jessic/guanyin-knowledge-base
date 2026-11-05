"""Build a separate video result page and link it from the existing source dashboard.

Does not alter video_extractor.py or any existing video data.
"""
from __future__ import annotations
import argparse
import csv
import html
import json
import re
import shutil
from pathlib import Path
from urllib.parse import parse_qs, urlparse


def video_id(url):
    p = urlparse(url)
    host = (p.hostname or '').lower()
    if host in {'youtu.be', 'www.youtu.be'}:
        return p.path.strip('/').split('/')[0]
    if host in {'youtube.com', 'www.youtube.com', 'm.youtube.com'}:
        if p.path == '/watch':
            return parse_qs(p.query).get('v', [''])[0]
        parts = p.path.strip('/').split('/')
        if len(parts) > 1 and parts[0] in {'shorts', 'embed', 'live'}:
            return parts[1]
    return ''


def load_records(path):
    result = {}
    if not path.is_file():
        return result
    with path.open(encoding='utf-8-sig') as f:
        for line in f:
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get('type') != 'video':
                continue
            vid = (rec.get('metadata') or {}).get('video_id') or video_id(rec.get('source_url', ''))
            if not vid and rec.get('id', '').startswith('video_'):
                vid = rec['id'][6:]
            if vid:
                result[vid] = rec
    return result


def esc(s):
    return html.escape(str(s if s is not None else ''), quote=True)


def build(root='.', output='site/videos.html', update_index=True):
    root = Path(root)
    out = root / output
    out.parent.mkdir(parents=True, exist_ok=True)
    with (root / 'urls.csv').open(encoding='utf-8-sig', newline='') as f:
        video_sources = [r for r in csv.DictReader(f) if r.get('type') == 'video']
    records = load_records(root / 'output/index.jsonl')
    gallery = []
    counts = {'success': 0, 'failed': 0, 'none': 0}
    for src in video_sources:
        vid = video_id(src.get('url', ''))
        rec = records.get(vid)
        raw = str(rec.get('crawl_status', '')).lower() if rec else ''
        has_subtitle = bool(rec and rec.get('timestamps'))
        has_frames = bool(rec and rec.get('images'))
        success = bool(rec and raw.startswith('success') and (has_subtitle or has_frames))
        failed = bool(rec and ('failed' in raw or '失敗' in raw))
        status = 'success' if success else 'failed' if failed else 'none'
        counts[status] += 1
        label = {'success': '已有影片成果', 'failed': '已執行但失敗', 'none': '尚無成果紀錄'}[status]
        subtitle_rows = (rec or {}).get('timestamps') or []
        images = (rec or {}).get('images') or []
        image_html = []
        for img in images:
            filename = Path(str(img.get('filename') or img.get('path', ''))).name
            src_image = root / 'output/images' / filename
            if not filename or not src_image.is_file():
                continue
            target = out.parent / 'assets/video' / filename
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_image, target)
            seconds = max(0, int(float(img.get('seconds') or 0)))
            link = f'https://www.youtube.com/watch?v={vid}&t={seconds}s'
            image_html.append(f'<a class="frame" href="{esc(link)}" target="_blank" rel="noopener"><img src="assets/video/{esc(filename)}" alt="代表畫面 {esc(img.get("timestamp", ""))}" loading="lazy"><span>{esc(img.get("timestamp", ""))} · {esc(img.get("description", ""))}</span></a>')
        subtitle_html = ''.join(f'<tr class="caption-row"><td>{esc(seg.get("start", ""))}</td><td>{esc(seg.get("text", ""))}</td></tr>' for seg in subtitle_rows)
        count_text = f'{len(subtitle_rows):,} 段字幕 · {len(images)} 張代表畫面'
        reason = '' if success else esc(rec.get('crawl_status', '') if rec else 'GitHub／本機尚無這支影片的成果紀錄')
        gallery.append(f'''<article class="video-card"><div class="vid-top"><span class="pill {status}">{label}</span><code>{esc(src.get('id', ''))}</code></div><h2>{esc(rec.get('title') if rec else 'YouTube 影片 '+vid)}</h2><div class="meta">{esc(count_text if rec else '尚未取得影片內容')}</div><p><a href="{esc(src.get('url', ''))}" target="_blank" rel="noopener noreferrer">開啟 YouTube 原始影片</a></p>{f'<p class="reason">{reason}</p>' if reason else ''}<div class="frames">{''.join(image_html)}</div>{f'<details class="captions"><summary>展開全部 {len(subtitle_rows):,} 段字幕</summary><label class="caption-search-label">搜尋時間或字幕 <input class="caption-search" placeholder="輸入文字或時間（例如 00:40）" aria-label="搜尋字幕" type="search"></label><p class="caption-count">目前顯示 {len(subtitle_rows):,} / {len(subtitle_rows):,} 段</p><div class="caption-table-wrap"><table><thead><tr><th>時間</th><th>字幕內容</th></tr></thead><tbody>{subtitle_html}</tbody></table></div></details>' if subtitle_rows else ''}</article>''')
    page = '''<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>觀音地方知識｜影片成果</title><style>
:root{font-family:system-ui,"Microsoft JhengHei",sans-serif;color:#343143;background:#f8f7fb}*{box-sizing:border-box}body{margin:0}.wrap{max-width:1100px;margin:auto;padding:40px 24px 70px}h1{font-size:34px}a{color:#62587f}.subtitle{color:#666179;line-height:1.7}.back{display:inline-block;margin:4px 0 20px;text-decoration:none}.stats{display:flex;gap:12px;flex-wrap:wrap;margin:24px 0}.stat{background:white;border:1px solid #e4e0eb;border-radius:14px;padding:16px 24px;min-width:165px}.stat strong{display:block;font-size:30px}.stat span{font-size:13px;color:#777181}.video-card{background:white;border:1px solid #e5e2eb;border-radius:18px;padding:24px;margin-bottom:18px}.video-card h2{font-size:20px;line-height:1.45}.vid-top{display:flex;justify-content:space-between;align-items:center;gap:10px}.pill{border-radius:20px;padding:6px 12px;font-size:12px;font-weight:650}.pill.success{background:#e5f2ea;color:#246f54}.pill.failed{background:#f9e8e6;color:#974c45}.pill.none{background:#f5eddf;color:#87621f}.meta,.reason{color:#777181;font-size:13px}.frames{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin:16px 0}.frame{display:block;text-decoration:none;border:1px solid #e6e2ed;border-radius:12px;overflow:hidden}.frame img{display:block;width:100%;aspect-ratio:16/9;object-fit:cover}.frame span{display:block;font-size:12px;padding:8px 10px;line-height:1.6}details{margin-top:15px}summary{cursor:pointer;color:#554b76;padding:10px 0;font-weight:650}.caption-search-label{display:block;font-size:13px;color:#777181;margin:12px 0}.caption-search{display:block;margin-top:8px;border:1px solid #dcd5e8;border-radius:9px;width:100%;padding:12px;font:inherit}.caption-count{font-size:12px;color:#777181}.caption-table-wrap{max-height:540px;overflow:auto;border:1px solid #eee9f1;border-radius:10px}table{border-collapse:collapse;width:100%;font-size:13px}td,th{text-align:left;vertical-align:top;padding:9px;border-bottom:1px solid #eee9f1}th:first-child{width:80px}footer{color:#6e6b7b;font-size:12px;margin-top:25px;line-height:1.7}
</style></head><body><main class="wrap"><a class="back" href="index.html">← 返回來源管理首頁</a><div class="subtitle">GUANYIN LOCAL KNOWLEDGE BASE · VIDEO RESULTS</div><h1>觀音地方知識｜影片成果</h1><p class="subtitle">直接讀取 <code>output/index.jsonl</code> 中的影片處理紀錄，顯示已驗證存在的字幕與畫面。影片處理程式已存在，不代表所有影片均成功。代表畫面來自原始影片擷取，僅用於課堂成果展示。</p><section class="stats"><div class="stat"><strong>__TOTAL__</strong><span>影片來源</span></div><div class="stat"><strong>__SUCCESS__</strong><span>有字幕或畫面的成功結果</span></div><div class="stat"><strong>__FAILED__</strong><span>已有失敗紀錄</span></div><div class="stat"><strong>__NONE__</strong><span>尚無可確認成果</span></div></section>__CARDS__<footer>本頁是本機靜態成果，重新處理影片後請再次執行 <code>py -3.12 -m crawler.video_site</code>。圖片只有在本機找到實際檔案時才會顯示，不會虛構影格。</footer></main><script>document.querySelectorAll('.captions').forEach(box=>{const search=box.querySelector('.caption-search');const rows=[...box.querySelectorAll('.caption-row')];const label=box.querySelector('.caption-count');const total=rows.length;search.addEventListener('input',()=>{const q=search.value.trim().toLocaleLowerCase();let found=0;for(const row of rows){const visible=!q||row.textContent.toLocaleLowerCase().includes(q);row.hidden=!visible;if(visible)found++}label.textContent=`目前顯示 ${found.toLocaleString()} / ${total.toLocaleString()} 段`;});});</script></body></html>'''
    page = (page.replace('__TOTAL__', str(len(video_sources))).replace('__SUCCESS__', str(counts['success']))
            .replace('__FAILED__', str(counts['failed'])).replace('__NONE__', str(counts['none']))
            .replace('__CARDS__', '\n'.join(gallery)))
    out.write_text(page, encoding='utf-8')
    index = out.parent / 'index.html'
    if update_index and index.is_file():
        text = index.read_text(encoding='utf-8')
        marker = '<!-- VIDEO_RESULTS_LINK -->'
        if marker not in text:
            link = '<div style="margin:16px 0 22px"><a href="videos.html" style="display:inline-block;padding:12px 18px;border:1px solid #d9d2e5;border-radius:12px;text-decoration:none;color:#504476;background:#fff">🎬 查看影片字幕、代表畫面及處理結果</a></div>'
            if '<section id="stats"' in text:
                text = text.replace('<section id="stats"', marker+link+'<section id="stats"',1)
            else:
                text = text.replace('</main>', marker+link+'</main>',1)
            index.write_text(text, encoding='utf-8')
    print('已生成影片成果頁：', out)
    print(f"影片來源 {len(video_sources)} 筆：有成果 {counts['success']}、失敗 {counts['failed']}、未確認 {counts['none']}")
    print('提醒：先執行 build_site，再執行 video_site，以保留首頁影片連結。')
    return counts


def main():
    p=argparse.ArgumentParser(description='建立觀音影片成果展示頁並加到來源首頁')
    p.add_argument('--root', default='.')
    p.add_argument('--output', default='site/videos.html')
    a=p.parse_args()
    build(root=a.root, output=a.output)

if __name__=='__main__': main()
