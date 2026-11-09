"""新增文章與圖片展示頁；不修改其他組員的爬蟲或知識庫資料。從專案根目錄執行。"""
from pathlib import Path
import json
import shutil
import re
import html

ROOT = Path.cwd()
ARTICLES = ROOT / 'output' / 'articles'
IMAGES = ROOT / 'output' / 'images'
SITE = ROOT / 'site'
TARGET = SITE / 'articles.html'
ASSETS = SITE / 'assets' / 'articles'


def load_records():
    records = []
    if not ARTICLES.is_dir():
        raise SystemExit('找不到 output/articles，請先確認已下載組員的文章成果。')
    for fp in sorted(ARTICLES.glob('*.json')):
        try:
            d = json.loads(fp.read_text(encoding='utf-8-sig'))
            if not isinstance(d, dict):
                continue
            items = []
            for item in d.get('images', []):
                if not isinstance(item, dict):
                    continue
                name = Path(str(item.get('file', '')).replace('\\', '/')).name
                source = IMAGES / name
                if not name or not source.is_file():
                    continue
                ASSETS.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, ASSETS / name)
                items.append({'path': f'assets/articles/{name}',
                              'caption': str(item.get('caption') or ''),
                              'original': str(item.get('source_url') or '')})
            records.append({'id': str(d.get('id') or fp.stem),
                            'title': str(d.get('title') or fp.stem),
                            'author': str(d.get('author') or ''),
                            'published': str(d.get('published_at') or ''),
                            'source': str(d.get('source_url') or ''),
                            'status': str(d.get('processing_status') or d.get('content_status') or ''),
                            'reason': str(d.get('processing_reason') or ''),
                            'content': str(d.get('content') or ''),
                            'images': items})
        except (ValueError, OSError) as e:
            print(f'略過 {fp.name}：{e}')
    return records


def update_navigation():
    # 只動既有的共用導覽區，不改任何頁面的功能、核心 JS 或爬蟲程式。
    navlink = '<a href="articles.html">文章與圖片</a>'
    for name in ('index.html', 'videos.html', 'video_quality.html',
                 'video_recovery.html', 'knowledge.html'):
        page = SITE / name
        if not page.is_file():
            continue
        content = page.read_text(encoding='utf-8-sig')
        pat = re.compile(r'(<!-- GUANYIN_VIDEO_TABS_START -->.*?<nav\b[^>]*>)(.*?)(</nav>.*?<!-- GUANYIN_VIDEO_TABS_END -->)', re.S | re.I)
        def add(m):
            if 'href="articles.html"' in m.group(2) or "href='articles.html'" in m.group(2):
                return m.group(0)
            return m.group(1) + m.group(2) + navlink + m.group(3)
        new = pat.sub(add, content, count=1)
        if new != content:
            page.write_text(new, encoding='utf-8')
            print(f'新增導覽：site/{name}')
        elif not pat.search(content):
            print(f'注意：site/{name} 未找到共用導覽標記，沒有改動。')


def main():
    rows = load_records()
    SITE.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(rows, ensure_ascii=False).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
    page = '''<!DOCTYPE html><html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>觀音地方知識｜文章與圖片</title>
<style>
:root{color-scheme:light;--ink:#332d42;--accent:#66547f;--line:#e7e0ed;--muted:#797081}
*{box-sizing:border-box}body{margin:0;background:#f8f6fa;color:var(--ink);font-family:system-ui,'Microsoft JhengHei',sans-serif}
nav{display:flex;flex-wrap:wrap;gap:9px;background:#fff;border-bottom:1px solid var(--line);padding:16px max(16px,calc((100vw - 1100px)/2))}nav a{color:var(--accent);text-decoration:none;padding:7px 10px;border-radius:7px}nav a[aria-current]{background:#ede7f4;font-weight:bold}
main{max-width:1100px;margin:auto;padding:36px 18px 75px}h1{font-size:clamp(27px,4vw,40px);margin:9px 0}.lead{color:var(--muted);line-height:1.85}input{width:100%;font:inherit;padding:13px;border:1px solid #ccc2da;border-radius:12px;margin:15px 0}#count{color:var(--muted);font-size:13px;margin:4px 0 17px}
article{background:#fff;border:1px solid var(--line);border-radius:17px;padding:23px;margin:0 0 18px}h2{font-size:21px;margin:7px 0 9px}.meta{color:var(--muted);font-size:12px;overflow-wrap:anywhere;line-height:1.7}.meta a{color:var(--accent)}.status{color:#7d5427}.content{white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.9;max-height:260px;overflow:auto;background:#faf9fc;padding:14px;border-radius:10px;font-size:14px}.images{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:12px;margin:18px 0 0}.images figure{margin:0;border:1px solid var(--line);border-radius:11px;overflow:hidden}.images img{display:block;width:100%;aspect-ratio:16/10;object-fit:contain;background:#f5f3f7}.images figcaption{padding:9px 11px;font-size:12px;line-height:1.55;color:var(--muted)}.images a{color:inherit}details{margin-top:15px}summary{cursor:pointer;color:var(--accent);font-weight:bold}small{color:var(--muted)}
</style></head><body>
<nav aria-label="網站主要分頁"><a href="index.html">來源管理</a><a href="articles.html" aria-current="page">文章與圖片</a><a href="videos.html">影片成果</a><a href="video_quality.html">影音分析</a><a href="video_recovery.html">影片成果 2</a><a href="knowledge.html">知識庫</a></nav>
<main><small>GUANYIN LOCAL KNOWLEDGE BASE</small><h1>文章與圖片｜爬蟲成果</h1><p class="lead">展示組員擷取並清理的文字與圖片。部分文章可能包含表格語法或網站殘留文字；此頁展示爬取內容，不代表所有事實均已查證。原文與圖片來源可點連結追溯。</p><input type="search" id="q" aria-label="搜尋文章" placeholder="搜尋文章標題、正文或來源 ID"><div id="count"></div><section id="results"></section></main>
<script>const records=/*RECORDS*/null;
const q=document.getElementById('q'),out=document.getElementById('results'),count=document.getElementById('count');
function el(tag,cls,text){const x=document.createElement(tag);if(cls)x.className=cls;if(text!==undefined)x.textContent=text;return x}
function link(url,label){try{const u=new URL(url);if(!['https:','http:'].includes(u.protocol))return null;const a=el('a',null,label);a.href=u.href;a.target='_blank';a.rel='noopener noreferrer';return a}catch{return null}}
function render(){const term=q.value.trim().toLocaleLowerCase();const matched=records.filter(r=>(r.title+' '+r.id+' '+r.content).toLocaleLowerCase().includes(term));out.replaceChildren();count.textContent=`顯示 ${matched.length} / ${records.length} 篇文章 · 共 ${matched.reduce((n,r)=>n+r.images.length,0)} 張可讀取圖片`;
for(const r of matched){const card=el('article');card.append(el('div','meta',r.id+' · '+(r.status||'未標記狀態')),el('h2',null,r.title));const meta=el('div','meta',(r.author?'作者：'+r.author+'　':'')+(r.published?'發布：'+r.published+'　':''));const l=link(r.source,'查看原始網頁');if(l)meta.append(' · ',l);card.append(meta);
if(r.content){const details=el('details');const summary=el('summary',null,'展開爬取正文（'+r.content.length+' 字元）');details.append(summary,el('div','content',r.content));card.append(details)}else card.append(el('p','status','尚無擷取到可用的正文'));
if(r.reason)card.append(el('p','status','處理說明：'+r.reason));if(r.images.length){const gallery=el('div','images');for(const i of r.images){const figure=el('figure');const a=el('a');a.href=i.path;a.target='_blank';a.rel='noopener';const img=el('img');img.src=i.path;img.loading='lazy';img.alt=i.caption||r.title;a.append(img);const cap=el('figcaption',null,i.caption||'文章圖片');const original=link(i.original,'原始圖片');if(original)cap.append(' · ',original);figure.append(a,cap);gallery.append(figure)}card.append(gallery)}else card.append(el('p','meta','沒有儲存成功的文章圖片'));out.append(card)}}}
q.addEventListener('input',render);render();</script></body></html>'''
    TARGET.write_text(page.replace('/*RECORDS*/null', payload), encoding='utf-8')
    update_navigation()
    print(f'完成：{TARGET}｜{len(rows)} 篇文章、{sum(len(r["images"]) for r in rows)} 張可讀取圖片')
    print('打開方式：在專案根目錄執行 py -3.12 -m http.server 8000，再前往 http://localhost:8000/site/articles.html')

if __name__ == '__main__':
    main()
