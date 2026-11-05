"""建立多軌處理時間軸；寫入 site/video_quality.html，不改組員的 Python 程式。"""
from __future__ import annotations
import argparse
import csv
import html
import json
import shutil
from pathlib import Path


def build(root='.'):
    root=Path(root)
    folder=root/'output/video_multimodal'
    if not folder.is_dir():raise RuntimeError('找不到 output/video_multimodal：請先執行 py -3.12 -m crawler.video_multimodal')
    videos=[]
    for p in sorted(folder.glob('*.json')):
        if p.name=='summary.json':continue
        try:rec=json.loads(p.read_text(encoding='utf-8'))
        except (UnicodeError,json.JSONDecodeError):continue
        if not isinstance(rec,dict) or not rec.get('id'):continue
        images=[]
        for img in rec.get('images',[]):
            name=Path(str(img.get('filename') or img.get('path') or '')).name
            if not name:continue
            original=root/'output/images'/name
            if not original.is_file():continue
            dest=root/'site/assets/video'/name
            dest.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(original,dest)
            images.append(dict(img,site_path='assets/video/'+name))
        rec['images']=images
        videos.append(rec)
    # 防止不受信任的文字令 JSON script 標籤提早結束。
    embedded=json.dumps(videos,ensure_ascii=False).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026').replace('\u2028','\\u2028')
    page='''<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>觀音地方學｜影音分析</title>
<style>
:root{font-family:system-ui,"Microsoft JhengHei",sans-serif;background:#f8f7fb;color:#383243}*{box-sizing:border-box}body{margin:0}main{max-width:1240px;margin:auto;padding:28px 20px 70px}a{color:#645480}h1{font-size:clamp(24px,4vw,38px);margin:12px 0 6px}h2{font-size:21px}.sub{color:#706a7c;line-height:1.7}.nav{display:flex;gap:16px;flex-wrap:wrap}.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(135px,1fr));gap:10px;margin:24px 0}.tile,.left,.right{background:white;border:1px solid #e5e1ec;border-radius:15px;padding:15px}.tile b{font-size:27px;display:block}.tile small,.dim{color:#706a7c}.layout{display:grid;grid-template-columns:minmax(200px,290px) minmax(0,1fr);gap:16px}.list{max-height:780px;overflow:auto}.pick{display:block;width:100%;text-align:left;border:1px solid transparent;background:#f5f2f8;border-radius:10px;padding:11px;margin:5px 0;cursor:pointer;font:inherit;color:inherit}.pick.sel{border-color:#7e71a4;background:#eeebf6}.pick small{display:block;color:#716c7b;margin-top:5px}.stage{display:grid;grid-template-columns:22px 1fr;gap:10px;margin:8px 0}.dot{height:16px;width:16px;border-radius:50%;margin-top:4px;background:#aca5b7}.dot.done{background:#618e7a}.dot.failed{background:#ad6262}.flow{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:9px}.flow .stage{background:#f8f6fa;border:1px solid #e9e4ef;padding:10px;border-radius:10px}.stage strong{font-size:13px}.stage p{font-size:12px;color:#706a7c;margin:4px 0}.multitrack{overflow-x:auto}.trackrow{display:grid;grid-template-columns:92px minmax(380px,1fr);align-items:center;gap:7px;margin:8px 0}.trackrow label{font-size:12px;color:#6c6576}.track{height:24px;border-radius:5px;background:#f1eff3;position:relative;overflow:hidden}.span{position:absolute;top:2px;bottom:2px;border-radius:3px;min-width:2px;cursor:pointer;border:0}.span.audio-speech{background:#669f8e}.span.audio-music{background:#b3a0cc}.span.audio-noise,.span.audio-silence{background:#c5c5c9}.span.cc{background:#6389bc}.span.ocr{background:#d9a05b}.span.trans{background:#90ae73}.span.img{background:#c47b9f}.legend{font-size:12px;color:#706a7c}.gridimgs{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:9px}.gridimgs img{width:100%;aspect-ratio:16/9;object-fit:cover}.gridimgs a{border:1px solid #e4dfeb;border-radius:10px;overflow:hidden;text-decoration:none}.gridimgs span{display:block;font-size:11px;padding:7px}.tabbar{display:flex;gap:6px;flex-wrap:wrap;margin:15px 0}.tabbar button{background:#f0edf6;border:1px solid #ddd7e7;padding:8px 11px;border-radius:8px;cursor:pointer}.tabbar button.active{background:#e1dbef}input{padding:9px;border:1px solid #ddd6e6;border-radius:9px;width:100%;font:inherit}.scroll{max-height:500px;overflow:auto;border:1px solid #ede8f1;border-radius:10px}table{width:100%;border-collapse:collapse;font-size:12px}th,td{border-bottom:1px solid #efeaf3;text-align:left;padding:8px;vertical-align:top}th{position:sticky;top:0;background:#f5f2f8}.muted{color:#857b91}.note{background:#faf8fc;border-left:3px solid #aaa1c5;padding:10px;font-size:13px;line-height:1.7}.link{display:inline-block;margin:8px 0}.small{font-size:12px}@media(max-width:760px){main{padding:16px 11px}.layout{grid-template-columns:1fr}.list{max-height:250px}.trackrow{grid-template-columns:74px minmax(320px,1fr)}.flow{grid-template-columns:repeat(2,minmax(0,1fr))}}
</style></head><body><main><nav class="nav"><a href="index.html">來源管理首頁</a><a href="videos.html">影片原始成果</a></nav><p class="sub small">GUANYIN LOCAL KNOWLEDGE BASE · MULTIMODAL VIDEO</p><h1>影音文字與處理流程</h1><p class="sub">整合音訊分類、YouTube 字幕、Whisper、畫面 OCR 與翻譯。不同來源以獨立軌道呈現；顯示的文字仍須依原始影音與資料出處確認。流程紀錄時間為程式產生事件的時間，不是歷史抓取步驟的實際耗時。</p><section class="tiles" id="tiles"></section><div class="layout"><aside class="left list"><label>搜尋影片<input id="searchvideo" type="search" placeholder="影片名稱或 ID"></label><div id="choices"></div></aside><article class="right" id="details"></article></div><footer class="sub small">課堂研究展示，非商業用途。原始影音及影像權利歸原權利人所有；使用時須核對授權與來源。音訊模型對人聲與歌唱的區分並非百分之百準確。</footer></main><script id="dataset" type="application/json">__DATA__</script>
<script>
const DATA=JSON.parse(document.getElementById('dataset').textContent);let current=0;let tab='subtitle_segments';const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));const arr=x=>Array.isArray(x)?x:[];const ss=x=>{let n=Number(x)||0;return n>=3600?`${Math.floor(n/3600)}:${String(Math.floor(n/60)%60).padStart(2,'0')}:${String(Math.floor(n%60)).padStart(2,'0')}`:`${String(Math.floor(n/60)).padStart(2,'0')}:${String(Math.floor(n%60)).padStart(2,'0')}`};
function tiles(){const sums=[['影片數',DATA.length],['可用文字片段',DATA.reduce((n,d)=>n+arr(d.subtitle_segments).length,0)],['畫面文字片段',DATA.reduce((n,d)=>n+arr(d.ocr_segments).length,0)],['音樂／歌詞隔離',DATA.reduce((n,d)=>n+arr(d.excluded_subtitles).length,0)]];document.getElementById('tiles').innerHTML=sums.map(x=>`<div class="tile"><b>${x[1].toLocaleString()}</b><small>${x[0]}</small></div>`).join('')}
function choices(){const q=document.getElementById('searchvideo').value.toLowerCase();document.getElementById('choices').innerHTML=DATA.map((d,i)=>(d.id+' '+d.title).toLowerCase().includes(q)?`<button class="pick ${i===current?'sel':''}" data-idx="${i}">${esc(d.title)}<small>${esc(d.id)} · CC/語音 ${arr(d.subtitle_segments).length} · OCR ${arr(d.ocr_segments).length}</small></button>`:'').join('');document.querySelectorAll('[data-idx]').forEach(e=>e.onclick=()=>{current=Number(e.dataset.idx);choices();details()})}
function events(d){return `<h2>處理流程紀錄</h2><div class="flow">${arr(d.events).map(e=>`<div class="stage"><span class="dot ${e.status==='done'?'done':e.status==='failed'?'failed':''}"></span><div><strong>${esc(e.name)}</strong><p>${esc(e.detail)}</p><p>${esc(e.recorded_at||'')}</p></div></div>`).join('')}</div>`}
function timeline(d){const dur=Math.max(Number(d.duration)||0,...['audio_segments','subtitle_segments','ocr_segments','translations'].flatMap(k=>arr(d[k]).map(x=>Number(x.end_seconds)||0)),1);const tracks=[['聲音',arr(d.audio_segments).map(x=>({...x,kind:'audio-'+(x.type||'noise')}))],['字幕',arr(d.subtitle_segments).map(x=>({...x,kind:'cc'}))],['畫面 OCR',arr(d.ocr_segments).map(x=>({...x,kind:'ocr'}))],['翻譯',arr(d.translations).map(x=>({...x,kind:'trans'}))],['圖片',arr(d.images).map(x=>({start_seconds:Number(x.seconds)||0,end_seconds:(Number(x.seconds)||0)+Math.max(dur*.006,1),text:x.description||'',kind:'img'}))]];return `<h2>影片內容多軌時間軸</h2><div class="multitrack">${tracks.map(([name,items])=>`<div class="trackrow"><label>${name} (${items.length})</label><div class="track">${items.slice(0,2500).map(x=>{const a=Math.max(0,Math.min(100,(Number(x.start_seconds)||0)/dur*100));const b=Math.max(a+.3,Math.min(100,(Number(x.end_seconds)||Number(x.start_seconds)||0)/dur*100));return `<button class="span ${esc(x.kind)}" style="left:${a.toFixed(2)}%;width:${Math.max(.3,b-a).toFixed(2)}%" title="${esc(ss(x.start_seconds)+' '+(x.text||x.type||''))}"></button>`}).join('')}</div></div>`).join('')}</div><p class="legend">音訊：綠＝人聲、紫＝音樂。藍＝字幕、橘＝OCR、綠黃＝翻譯、粉＝代表畫面。點選區間可查看時間與簡介。</p><p class="dim small">00:00　～　${ss(dur)}</p>`}
const tabnames={subtitle_segments:'字幕／語音',ocr_segments:'畫面 OCR',translations:'翻譯結果',excluded_subtitles:'配樂與其他隔離文字'};
function rows(d){const active=arr(d[tab]);return `<h2>文字內容</h2><div class="tabbar">${Object.entries(tabnames).map(([key,name])=>`<button data-tab="${key}" class="${tab===key?'active':''}">${name} (${arr(d[key]).length})</button>`).join('')}</div><input id="searchtext" type="search" placeholder="搜尋文字與時間"><div class="scroll"><table><thead><tr><th>時間</th><th>來源</th><th>內容</th></tr></thead><tbody id="textbody"></tbody></table></div>`}
function fillRows(d){const q=(document.getElementById('searchtext')?.value||'').toLowerCase();document.getElementById('textbody').innerHTML=arr(d[tab]).filter(x=>((x.text||'')+' '+ss(x.start_seconds)).toLowerCase().includes(q)).slice(0,2500).map(x=>`<tr><td>${esc(ss(x.start_seconds))}</td><td>${esc(x.source||x.model||'')}</td><td>${esc(x.text)}</td></tr>`).join('')}
function details(){const d=DATA[current];if(!d){document.getElementById('details').textContent='尚無影片分析結果';return;}const url=String(d.source_url||'');const safe=/^https:\/\/(www\.)?(youtube\.com|youtu\.be)\//.test(url)?url:'#';document.getElementById('details').innerHTML=`<h2>${esc(d.title)}</h2><p class="sub">${esc(d.id)}　·　字幕來源：${esc(d.subtitle_source)}　·　分析模式：${d.audio_status==='done'?'有音訊分類紀錄':'未執行音訊模型'}</p><a class="link" target="_blank" rel="noopener noreferrer" href="${esc(safe)}">開啟 YouTube 原始影片</a><p class="note">保留 ${arr(d.subtitle_segments).length} 段字幕，另隔離 ${arr(d.excluded_subtitles).length} 段可能屬於配樂等內容；畫面文字 ${arr(d.ocr_segments).length} 段。這些是技術處理紀錄，不代表文字敘述已完成史實查證。</p>${events(d)}${timeline(d)}<h2>代表畫面</h2><div class="gridimgs">${arr(d.images).map(x=>`<a target="_blank" rel="noopener" href="${esc(safe+(safe.includes('?')?'&':'?')+'t='+Math.floor(Number(x.seconds)||0)+'s')}"><img loading="lazy" src="${esc(x.site_path)}" alt="${esc(x.description||'影片畫面')}"><span>${esc(x.timestamp||ss(x.seconds))}</span></a>`).join('')}</div>${rows(d)}`;document.querySelectorAll('[data-tab]').forEach(e=>e.onclick=()=>{tab=e.dataset.tab;details()});document.getElementById('searchtext').oninput=()=>fillRows(d);fillRows(d)}
document.getElementById('searchvideo').oninput=choices;tiles();choices();details();
</script></body></html>'''
    page=page.replace('__DATA__',embedded)
    destination=root/'site/video_quality.html';destination.parent.mkdir(parents=True,exist_ok=True)
    destination.write_text(page,encoding='utf-8')
    index=root/'site/index.html'
    if index.is_file():
        body=index.read_text(encoding='utf-8')
        link='<div id="MULTIMODAL_VIDEO_LINK" style="margin:15px 0"><a href="video_quality.html" style="display:inline-block;padding:12px;border:1px solid #d9d2e5;border-radius:10px;background:#fff;color:#554878;text-decoration:none">🎞️ 影音處理與多軌時間軸</a></div>'
        if 'id="MULTIMODAL_VIDEO_LINK"' not in body:
            body=body.replace('</main>',link+'</main>',1) if '</main>' in body else body.replace('</body>',link+'</body>',1)
            index.write_text(body,encoding='utf-8')
    print(f'多軌影片成果頁完成：{destination}（{len(videos)} 部）')
    return destination


def main():
    p=argparse.ArgumentParser();p.add_argument('--root',default='.');a=p.parse_args();build(a.root)
if __name__=='__main__':main()
