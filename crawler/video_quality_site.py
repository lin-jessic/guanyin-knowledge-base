"""觀音影音處理流程時間軸與品質查核：靜態離線 HTML（不啟動伺服器）。
請先執行 crawler.video_quality analyze，再執行本模組。
"""
from __future__ import annotations
import argparse
import html
import json
import shutil
from pathlib import Path
from .video_quality import sources, read_json

PAGE = r'''<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>觀音地方學｜影音品質與流程時間軸</title>
<style>
:root{font-family:system-ui,"Microsoft JhengHei",sans-serif;--ink:#34313f;--muted:#787184;--purple:#66577f;--border:#e5e0eb;--bg:#faf9fc;--good:#317d62;--warn:#9e7135;--bad:#a45355}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink)}main{max-width:1180px;margin:auto;padding:36px 22px 70px}h1{font-size:clamp(25px,3.5vw,39px);margin:7px 0}h2{font-size:21px}.muted{color:var(--muted);line-height:1.75}.tag{font-size:12px;letter-spacing:1.5px;color:var(--purple)}.nav a{color:var(--purple);margin-right:14px}.summary{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:22px 0}.tile{background:white;border:1px solid var(--border);border-radius:14px;padding:18px}.tile b{font-size:29px;display:block}.tile span{font-size:12px;color:var(--muted)}.columns{display:grid;grid-template-columns:minmax(240px,300px) minmax(0,1fr);gap:16px}.list,.panel{background:white;border:1px solid var(--border);border-radius:16px;padding:17px}.item{width:100%;border:1px solid transparent;background:#f7f5fa;text-align:left;border-radius:10px;padding:11px;margin:5px 0;cursor:pointer;color:var(--ink);font:inherit}.item.active{border-color:#aaa0c4;background:#eeeaf5}.item small{display:block;color:var(--muted);margin-top:5px;font-size:12px}.flag{display:inline-block;padding:5px 9px;border-radius:20px;font-size:11px;font-weight:700;background:#f0eef5;color:#65577d}.flag.good{background:#e4f3ed;color:#23694f}.flag.warn{background:#fcf0df;color:#88581d}.flag.bad{background:#f9e7e7;color:#9c4447}select,input{font:inherit;border:1px solid #ddd5e5;border-radius:9px;padding:10px;max-width:100%;width:100%;background:white}label{display:block;color:var(--muted);font-size:12px;margin:8px 0}section{margin:20px 0}.flow{display:grid;gap:10px;margin:12px 0}.step{display:grid;grid-template-columns:19px 1fr;gap:12px;position:relative}.step:not(:last-child):before{content:"";position:absolute;left:9px;top:19px;bottom:-12px;width:2px;background:#e7e1ee}.dot{width:19px;height:19px;border-radius:50%;background:#bbb4c7;position:relative;z-index:1}.dot.done{background:var(--good)}.dot.failed{background:var(--bad)}.dot.pending,.dot.skipped{background:#d5ae69}.steptext{background:#faf8fc;border:1px solid #ede9f1;padding:12px;border-radius:10px}.steptext strong{font-size:14px}.steptext p{font-size:12px;margin:4px 0;color:var(--muted)}.timeline{position:relative;border-radius:10px;background:#ede8f1;height:22px;overflow:hidden;margin:18px 0 8px}.ticks{position:absolute;height:100%;width:2px;top:0;background:var(--purple)}.ticks.ocr{background:#c58d3c}.legend{font-size:12px;color:var(--muted);margin-bottom:10px}.scroll{max-height:480px;overflow:auto;border:1px solid var(--border);border-radius:10px}table{width:100%;border-collapse:collapse;font-size:13px}th,td{padding:9px 10px;text-align:left;border-bottom:1px solid #eeeaf1;vertical-align:top}th{position:sticky;top:0;background:#f3eff7}td:first-child{white-space:nowrap;width:88px}.gallery{display:grid;grid-template-columns:repeat(auto-fit,minmax(175px,1fr));gap:10px;margin:14px 0}.gallery figure{border:1px solid var(--border);margin:0;border-radius:11px;overflow:hidden}.gallery img{width:100%;aspect-ratio:16/9;object-fit:cover;display:block}.gallery figcaption{font-size:12px;padding:7px}.notice{border-left:3px solid #b8adc9;padding:6px 12px;background:#faf8fc;font-size:13px;line-height:1.7}.pillbox{display:flex;gap:6px;flex-wrap:wrap}.small{font-size:12px}.break{overflow-wrap:anywhere}@media(max-width:800px){main{padding:20px 12px}.columns{grid-template-columns:1fr}.list{max-height:260px;overflow:auto}}
</style></head><body><main>
<nav class="nav"><a href="index.html">返回來源管理</a><a href="videos.html">影片成果及完整字幕</a></nav>
<div class="tag">GUANYIN LOCAL KNOWLEDGE BASE · VIDEO QUALITY</div><h1>影音資料品質與處理流程</h1>
<p class="muted">來源取得 → 字幕／OCR → 品質初篩 → 人工審核。此頁以既有 JSON 與抽查結果建立，流程階段標記是<b>處理證據狀態</b>，不是實際程式耗時。下方影片時間尺才是原始影片的內容時間。</p>
<div class="summary" id="summary"></div>
<div class="columns"><aside class="list"><label for="listfilter">篩選影片</label><input id="listfilter" type="search" placeholder="輸入 ID、標題或狀態"><div id="list"></div></aside>
<article class="panel"><div id="details"></div></article></div>
<footer class="muted small" style="margin-top:24px">本頁為課程非商業研究展示。自動字幕、OCR 與品質建議可能有誤；未經人工核准不得作為已查證的地方史料。影片及圖片各歸其原權利人所有，應核對授權與平台規範。</footer>
</main><script id="recordData" type="application/json">__DATA__</script>
<script>
const data=JSON.parse(document.querySelector('#recordData').textContent);
const $=s=>document.querySelector(s);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const states={needs_review:['字幕待審','warn'],suspected_music:['疑似音樂字幕','bad'],no_transcript:['無語音字幕','warn'],visual_only:['影像為主','warn'],failed:['來源失敗','bad'],unprocessed:['尚未處理','warn']};
function stateOf(r){return states[r.quality_state]||['已分析','warn']}
const total=data.length,images=data.reduce((a,r)=>a+r.image_count,0),subs=data.reduce((a,r)=>a+r.raw_subtitle_count,0),ocr=data.reduce((a,r)=>a+(r.ocr_texts||[]).length,0),approved=data.filter(r=>r.review_state==='approved').length;
$('#summary').innerHTML=[['來源影片',total],['原始字幕',subs],['代表畫面',images],['OCR 候選文字',ocr],['人工核准',approved]].map(([k,v])=>`<div class="tile"><b>${v.toLocaleString()}</b><span>${k}</span></div>`).join('');
let selected=data[0]?.id||'';
function drawList(){const q=$('#listfilter').value.trim().toLowerCase();$('#list').innerHTML=data.filter(r=>[r.id,r.title,r.quality_state].join(' ').toLowerCase().includes(q)).map(r=>`<button class="item ${r.id===selected?'active':''}" data-id="${esc(r.id)}"><strong>${esc(r.id)}</strong><small>${esc(r.title)}</small><small>${esc(stateOf(r)[0])}｜${r.raw_subtitle_count} 字幕｜${r.image_count} 圖</small></button>`).join('');$('#list').querySelectorAll('.item').forEach(e=>e.addEventListener('click',()=>{selected=e.dataset.id;drawList();drawDetails()}))}
function timeline(r){const marks=[...(r.raw_timestamps||[]).map(s=>({n:Number(s.start_seconds)||0,type:'speech'})),...(r.ocr_texts||[]).map(s=>({n:Number(s.start_seconds)||0,type:'ocr'}))];const duration=Math.max(1,Number(r.duration)||0,...marks.map(m=>m.n+1));return `<div class="timeline" aria-label="影音內容時間分布">${marks.map(m=>`<span title="${esc(m.type)} ${esc(m.n)}s" class="ticks ${m.type==='ocr'?'ocr':''}" style="left:${Math.min(99.7,100*m.n/duration).toFixed(2)}%"></span>`).join('')}</div><div class="legend">紫色：字幕段落時間位置 · 金色：OCR 畫面文字位置 · 影片長度約 ${Math.round(duration)} 秒</div>`}
function tableRows(arr,kind){return `<div class="scroll"><table><thead><tr><th>影片時間</th><th>${kind==='ocr'?'OCR 畫面文字（未校正）':'原始字幕（未校正）'}</th></tr></thead><tbody>${arr.map(s=>`<tr class="entry"><td>${esc(s.start||'')}</td><td>${esc(s.text||'')}</td></tr>`).join('')}</tbody></table></div>`}
function drawDetails(){const r=data.find(d=>d.id===selected);if(!r){$('#details').textContent='沒有影片資料';return}const [label,cls]=stateOf(r);let view=`<div class="pillbox"><span class="flag ${cls}">${esc(label)}</span><span class="flag ${r.review_state==='approved'?'good':'warn'}">人工審核：${esc(r.review_state||'pending')}</span></div><h2>${esc(r.title)}</h2><p class="small muted">來源：<a href="${esc(r.source_url)}" rel="noopener noreferrer" target="_blank">YouTube 原始影片</a> · ID：${esc(r.id)} · 原始狀態：${esc(r.raw_crawl_status)}</p><div class="notice">${esc(r.quality_reason)}${r.warnings?.length?'；'+r.warnings.map(esc).join('；'):''}<br>注意：影片畫面與歌詞不自動等於地方事實。${r.review_note?'人工審核註記：'+esc(r.review_note):''}</div>`;
view+=`<section><h2>處理流程時間軸</h2><div class="flow">${(r.stages||[]).map((s,i)=>`<div class="step"><span class="dot ${esc(s.status)}"></span><div class="steptext"><strong>${i+1}. ${esc(s.step)}</strong><p>${esc(s.detail)}</p></div></div>`).join('')}</div><p class="muted small">目前程式尚未保存每一步的開始、結束與實際耗時；此處不會虛構執行時間。</p></section>`;
view+=`<section><h2>影片內容時間軸</h2>${timeline(r)}</section>`;
view+=`<section><h2>代表畫面 (${r.image_count})</h2><div class="gallery">${(r.image_assets||[]).map(x=>`<figure><img src="${esc(x.src)}" loading="lazy" alt="${esc(x.caption)}"><figcaption>${esc(x.caption)}</figcaption></figure>`).join('')||'<p class="muted">本機未找到可展示的圖片檔案</p>'}</div></section>`;
const ocrRows=r.ocr_texts||[],raw=r.raw_timestamps||[];
view+=`<section><h2>字幕與 OCR 原始文字</h2><div class="pillbox"><span class="flag">原始字幕 ${raw.length}</span><span class="flag">候選字幕 ${(r.candidate_timestamps||[]).length}</span><span class="flag">排除音樂/重複提示 ${r.excluded_subtitle_count||0}</span><span class="flag">OCR ${ocrRows.length}</span><span class="flag">字幕來源 ${esc(r.subtitle_source)}</span></div><label>搜尋本影片字幕或 OCR <input id="textSearch" type="search" placeholder="輸入關鍵字、地名或時間"></label><h3>保守清理後候選字幕（尚未人工核對）</h3><div id="candidateTable">${tableRows(r.candidate_timestamps||[],'speech')}</div><details><summary>展開全部原始字幕（包含英文歌詞與錯誤辨識）</summary><div id="speechTable">${tableRows(raw,'speech')}</div></details><h3>畫面文字 OCR</h3><div id="ocrTable">${tableRows(ocrRows,'ocr')}</div></section>`;
$('#details').innerHTML=view;const q=$('#textSearch');q.addEventListener('input',()=>{const v=q.value.trim().toLowerCase();for(const t of ['#speechTable','#candidateTable','#ocrTable'])$(t).querySelectorAll('.entry').forEach(tr=>tr.hidden=!!v&&!tr.textContent.toLowerCase().includes(v))});}
$('#listfilter').addEventListener('input',drawList);drawList();drawDetails();
</script></body></html>'''


def create(root='.', output='site/video_quality.html'):
    root=Path(root)
    outputs=root/'output/video_quality'
    rows=[]
    out=root/output
    out.parent.mkdir(parents=True,exist_ok=True)
    for source in sources(root):
        rec=read_json(outputs/f'{source["id"]}.json',None)
        if rec is None:continue
        rec=dict(rec)
        rec['duration']=0
        # actual video duration stored in original record, not guessed from timestamps
        raw=read_json(root/'output/videos'/f'{source["id"]}.json',{})
        rec['duration']=(raw.get('metadata') or {}).get('duration') or 0
        assets=[]
        for im in rec.get('images',[]):
            name=Path(str(im.get('filename') or im.get('path') or '')).name
            if not name:continue
            original=root/'output/images'/name
            if not original.is_file():continue
            target=out.parent/'assets/video_quality'/name
            target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(original,target)
            assets.append(dict(src=f'assets/video_quality/{name}',caption=f"{im.get('timestamp','')} · {im.get('description','代表畫面')}"))
        rec['image_assets']=assets
        rows.append(rec)
    payload=json.dumps(rows,ensure_ascii=False).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
    out.write_text(PAGE.replace('__DATA__',payload),encoding='utf-8')
    for linkfile in (out.parent/'index.html',out.parent/'videos.html'):
        if not linkfile.is_file():continue
        s=linkfile.read_text(encoding='utf-8')
        if 'href="video_quality.html"' in s:continue
        link='<p style="margin:15px 0"><a href="video_quality.html" style="display:inline-block;padding:11px 15px;border:1px solid #bcb2cf;border-radius:10px;background:white;color:#554778;text-decoration:none">📊 查看影音處理時間軸與品質審核</a></p>'
        if '<main' in s:
            pos=s.find('>',s.index('<main'))+1
            s=s[:pos]+link+s[pos:]
        else:s=s.replace('</body>',link+'</body>',1)
        linkfile.write_text(s,encoding='utf-8')
    print(f'影音品質網站已建立：{out}，共有 {len(rows)} 部影片')
    print('已將品質頁入口連到現有首頁與影片成果頁（若檔案存在）')
    return out


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--root',default='.')
    p.add_argument('--output',default='site/video_quality.html')
    a=p.parse_args()
    create(a.root,a.output)

if __name__=='__main__':main()
