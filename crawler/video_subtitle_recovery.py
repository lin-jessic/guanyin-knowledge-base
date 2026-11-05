"""補救作者燒錄字幕：上下文保留、字幕優先、客語不亂轉中文。

Run: py -3.12 -m crawler.video_subtitle_recovery --ocr --interval 1
No modifications to original output/videos, output/index.jsonl, or teammate code.
"""
from __future__ import annotations
import argparse, csv, html, json, re
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path

try:
    from .video_quality import sources, find_record, locate_media, read_json, save_json
except ImportError as exc:
    raise RuntimeError('請將本檔放在既有專案的 crawler/ 資料夾') from exc

HAN=re.compile(r'[\u3400-\u9fff]')
MARKER=re.compile(r'^\s*(\[(?:music|singing|instrumental|applause)[^]]*\]|[♫♪♬\s])+\s*$',re.I)


def normalize(text):
    text=' '.join(str(text).split())
    try:
        from opencc import OpenCC
        # cached singleton; avoid model setup per OCR line
        if not hasattr(normalize,'cc'): normalize.cc=OpenCC('s2twp')
        text=normalize.cc.convert(text)
    except ImportError: pass
    return text


def media_seconds(record):
    return float((record.get('metadata') or {}).get('duration') or 0)


def ocr_subtitles(path, interval=1.0, max_frames=2400, crop_top=.50, min_conf=.48):
    """優先掃描常見字幕區域，額外掃描全畫面以保留地點標題。
    先跨幀去重，再依字形相似及相對位置合併，避免每秒重複。
    """
    try:
        import cv2
        from rapidocr_onnxruntime import RapidOCR
    except ImportError as e:
        raise RuntimeError('請安裝 rapidocr-onnxruntime opencv-python') from e
    capture=cv2.VideoCapture(str(path))
    if not capture.isOpened(): raise RuntimeError('無法讀取本機影片 '+str(path))
    fps=capture.get(cv2.CAP_PROP_FPS) or 25
    duration=capture.get(cv2.CAP_PROP_FRAME_COUNT)/fps
    if duration<=0: capture.release(); raise RuntimeError('影片長度不可用')
    engine=RapidOCR()
    segments=[]; active={}
    sample_count=min(max_frames,int(duration/interval)+1)
    try:
        for i in range(sample_count):
            t=i*interval
            if t>=duration:break
            capture.set(cv2.CAP_PROP_POS_MSEC,t*1000)
            ok,frame=capture.read()
            if not ok:continue
            h,w=frame.shape[:2]
            if w>1280:
                frame=cv2.resize(frame,(1280,round(h*1280/w)))
                h,w=frame.shape[:2]
            # 大部分作者內嵌字幕在下半部；每 8 秒全面掃描一次以辨識地名標題。
            modes=[('subtitle',int(h*crop_top),frame[int(h*crop_top):,:])]
            if i%max(1,round(8/interval))==0:modes.append(('title',0,frame[:int(h*crop_top),:]))
            seen=set()
            for kind,y_offset,part in modes:
                if part.size==0:continue
                result,_=engine(part)
                for item in result or []:
                    if len(item)<3:continue
                    box,raw,confidence=item[:3]
                    text=normalize(raw)
                    if len(text)<2 or float(confidence)<min_conf:continue
                    if not (HAN.search(text) or re.search(r'[A-Za-z]{4,}',text)):continue
                    mid_y=(sum(float(p[1]) for p in box)/len(box)+y_offset)/h
                    mid_x=sum(float(p[0]) for p in box)/len(box)/w
                    # Avoid many copies of text on same frame.
                    if text in seen:continue
                    seen.add(text)
                    key=(kind,round(mid_y*12),round(mid_x*5))
                    latest=active.get(key)
                    if latest and t-latest['last_seen']<=2*interval+0.1 and SequenceMatcher(None,latest['text'],text).ratio()>=.82:
                        latest['end_seconds']=round(min(duration,t+interval),2)
                        latest['last_seen']=t
                        latest['samples']+=1
                        latest['confidence']=max(latest['confidence'],round(float(confidence),3))
                    else:
                        rec={'text':text,'source':'ocr','kind':kind,
                             'start_seconds':round(t,2),'end_seconds':round(min(duration,t+interval),2),
                             'confidence':round(float(confidence),3),'samples':1,'last_seen':t,
                             'position':[round(mid_x,3),round(mid_y,3)]}
                        segments.append(rec);active[key]=rec
            for k in list(active):
                if t-active[k]['last_seen']>2*interval+.1:active.pop(k)
    finally:capture.release()
    for r in segments:r.pop('last_seen',None)
    # Small isolated OCR fragments likely to be artifacts; keep them internally in raw OCR file but
    # do not elevate them into displayed subtitle candidates.
    captions=[r for r in segments if r['kind']=='subtitle' and (r['samples']>=2 or len(r['text'])>=7)]
    titles=[r for r in segments if r['kind']=='title' and r['samples']>=1]
    return segments,captions,titles


def is_unreliable_asr(row):
    txt=str(row.get('text','')).strip()
    return (not txt or MARKER.fullmatch(txt) is not None or
            (not HAN.search(txt) and len(txt)>5 and re.search('[a-z]{3}',txt,re.I)))


def run(root='.', ids=None, do_ocr=False, interval=1., max_frames=2400):
    root=Path(root)
    rules=read_json(root/'data/video_recovery_rules.json',{})
    out=root/'output/video_recovery';out.mkdir(parents=True,exist_ok=True)
    records=[]
    for src in sources(root):
        sid=src['id']
        if ids and sid not in ids:continue
        original=find_record(root,src)
        if not original:continue
        prior=read_json(out/f'{sid}.json',{})
        mode=rules.get(sid,{}).get('mode','normal')
        origin_status=str(original.get('crawl_status',''))
        raw=original.get('timestamps') or []
        cc='youtube_vtt' in origin_status
        # VTT is not necessarily true speech (it may contain translated song lyrics).
        lyrics=mode=='music' or (cc and raw and sum(not HAN.search(str(x.get('text',''))) for x in raw)/len(raw)>.85)
        speech=[] if mode=='hakka' or lyrics else [dict(x,source='youtube_cc' if cc else 'whisper') for x in raw if not is_unreliable_asr(x)]
        media=locate_media(root,src)
        if do_ocr:
            if media:
                try:
                    ocr,captions,titles=ocr_subtitles(media,interval,max_frames)
                    ocr_status='done'
                except Exception as e:
                    ocr=prior.get('ocr_raw',[]);captions=prior.get('ocr_captions',[]);titles=prior.get('ocr_titles',[])
                    ocr_status='error: '+str(e)[:240]
            else:
                ocr=prior.get('ocr_raw',[]);captions=prior.get('ocr_captions',[]);titles=prior.get('ocr_titles',[])
                ocr_status='media_not_found'
        else:
            ocr=prior.get('ocr_raw',[]);captions=prior.get('ocr_captions',[]);titles=prior.get('ocr_titles',[])
            ocr_status=prior.get('ocr_status','not_run')
        # For Hakka speech, no Mandarin transcript is promoted. Burned captions are the primary source.
        # For all other videos, displayed groups are separately sourced, not merged into fake statements.
        rec={'id':sid,'title':original.get('title') or sid,'url':src.get('url'),
             'duration':media_seconds(original),'language_mode':mode,
             'cc_source':'youtube' if cc else 'whisper' if 'whisper' in origin_status else 'none',
             'ocr_status':ocr_status,'ocr_raw':ocr,'ocr_captions':captions,'ocr_titles':titles,
             'speech_subtitles':speech,'raw_subtitle_count':len(raw),'suppressed_asr':len(raw)-len(speech),
             'images':original.get('images') or [],
             'process':[{'name':'原始影音與字幕','count':len(raw)},
                        {'name':'影格 OCR','count':len(ocr)},
                        {'name':'畫面文字合併','count':len(captions)},
                        {'name':'字幕來源分流','count':len(speech)},
                        {'name':'保留原始來源','count':len(raw)}]}
        save_json(out/f'{sid}.json',rec);records.append(rec)
        print(f'{sid:10} | 模式 {mode:6} | OCR 字幕 {len(captions):4} | CC/語音 {len(speech):4} | {ocr_status}')
    save_json(out/'summary.json',[{'id':x['id'],'ocr_status':x['ocr_status'],'ocr_captions':len(x['ocr_captions'])} for x in records])
    return records


def build_site(root='.'):
    root=Path(root);records=[]
    for f in sorted((root/'output/video_recovery').glob('*.json')):
        if f.name=='summary.json':continue
        x=read_json(f,{})
        if x.get('id'):records.append(x)
    if not records:raise RuntimeError('請先執行爬蟲處理指令')
    payload=json.dumps(records,ensure_ascii=False).replace('<','\\u003c').replace('&','\\u0026')
    page=r'''<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>觀音地方學｜影片字幕與畫面文字</title><style>
:root{font:16px system-ui,'Microsoft JhengHei';color:#25283b;background:#f7f7fb}*{box-sizing:border-box}body{margin:0}main{max-width:1120px;margin:auto;padding:24px 16px 90px}h1{font-size:clamp(24px,4vw,36px)}h2{font-size:20px}.muted{color:#657187;font-size:13px}section,.card{background:white;border:1px solid #dde3ea;border-radius:14px;padding:18px;margin:16px 0}select{width:100%;padding:11px;border-radius:8px;border:1px solid #bbc7d3}a{color:#245c91}.bars{display:flex;gap:10px;flex-wrap:wrap}.bars>div{flex:1;min-width:100px;background:#eff3f8;border-radius:10px;padding:11px}.bars strong{font-size:24px;display:block}.trackrow{display:grid;grid-template-columns:95px minmax(0,1fr);gap:8px;align-items:center;margin:9px 0}.track{height:26px;position:relative;background:#edf0f5;border-radius:7px;overflow:hidden}.segment{position:absolute;top:4px;bottom:4px;background:#dcaa57;border-radius:3px;min-width:2px}.segment.speech{background:#6387b3}.timeline{margin:12px 0}table{border-collapse:collapse;width:100%}td,th{border-bottom:1px solid #e8ecf2;text-align:left;padding:9px;vertical-align:top}th{font-size:12px;color:#596579}.scroll{max-height:480px;overflow:auto}.flow{display:flex;gap:7px;flex-wrap:wrap}.flow span{background:#edf3ed;border-radius:7px;padding:9px;font-size:13px}button{border:1px solid #b9c6d2;background:#f5f8fd;border-radius:8px;padding:9px;cursor:pointer}button.active{background:#d8e6f8}@media(max-width:600px){.trackrow{grid-template-columns:70px minmax(0,1fr)}td,th{padding:7px;font-size:12px}}
</style></head><body><main><a href="index.html">返回首頁</a><h1>觀音地方學｜影片字幕與畫面文字</h1><p class="muted">優先呈現影片畫面文字與可用 CC；不同技術取得的文字分開保存。客語音訊不會被強制顯示成猜測的華語逐字稿。本文字來源只用於課堂研究，引用前仍須核對原始影音。</p><section><label for="video">選擇影片</label><select id="video"></select><div id="summary" class="bars"></div><p id="link"></p></section><section><h2>處理流程</h2><div id="steps" class="flow"></div></section><section><h2>影片時間軸</h2><div id="timeline" class="timeline"></div><p class="muted">橘色＝畫面字幕；藍色＝CC／語音來源。點擊區間可查看文字。</p></section><section><h2>擷取文字</h2><div id="tabs"></div><div class="scroll"><table><thead><tr><th>時間</th><th>來源</th><th>文字</th></tr></thead><tbody id="rows"></tbody></table></div></section><p class="muted">本網站為非商業課堂展示。影片與影像版權屬各原權利人；來源及內容的正確性需依原始資料核對。</p></main><script type="application/json" id="data">__DATA__</script><script>
const DATA=JSON.parse(document.getElementById('data').textContent);const el=id=>document.getElementById(id);const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));const time=s=>{s=Math.floor(Number(s)||0);return String(Math.floor(s/60)).padStart(2,'0')+':'+String(s%60).padStart(2,'0')};let idx=0,tab='ocr_captions';
el('video').innerHTML=DATA.map((v,i)=>`<option value="${i}">${esc(v.title)} (${esc(v.id)})</option>`).join('');el('video').onchange=e=>{idx=+e.target.value;tab='ocr_captions';draw()};
function track(name,items,dur,kind){return `<div class="trackrow"><small>${name} (${items.length})</small><div class="track">${items.map(s=>{let a=Math.min(100,100*(s.start_seconds||0)/dur),b=Math.min(100,100*(s.end_seconds||s.start_seconds||0)/dur);return `<span class="segment ${kind}" style="left:${a}%;width:${Math.max(.24,b-a)}%" title="${esc(time(s.start_seconds)+' '+s.text)}"></span>`}).join('')}</div></div>`}
function draw(){const v=DATA[idx];const a=v.ocr_captions||[],b=v.speech_subtitles||[];el('summary').innerHTML=[['原始字幕',v.raw_subtitle_count],['畫面字幕',a.length],['CC／語音',b.length],['地點標題',(v.ocr_titles||[]).length]].map(p=>`<div><strong>${p[1]}</strong><small>${p[0]}</small></div>`).join('');el('link').innerHTML=`<a href="${esc(/^https:\/\/www\.youtube\.com\/watch\?v=[\w-]+$/.test(v.url)?v.url:'#')}" target="_blank" rel="noopener">查看原始影片</a>　<span class="muted">OCR：${esc(v.ocr_status)}</span>`;el('steps').innerHTML=v.process.map(p=>`<span>${esc(p.name)}：${p.count}</span>`).join('');let dur=Math.max(v.duration||0,...a.map(x=>x.end_seconds||0),...b.map(x=>x.end_seconds||0),1);el('timeline').innerHTML=track('畫面字幕',a,dur,'')+track('CC／語音',b,dur,'speech')+`<p class="muted">00:00 ～ ${time(dur)}</p>`;const tabs=[['ocr_captions','作者畫面字幕'],['ocr_titles','地點／標題'],['speech_subtitles','CC／語音']];el('tabs').innerHTML=tabs.map(([k,n])=>`<button data-t="${k}" class="${k===tab?'active':''}">${n} (${(v[k]||[]).length})</button>`).join(' ');el('tabs').querySelectorAll('button').forEach(b=>b.onclick=()=>{tab=b.dataset.t;draw()});el('rows').innerHTML=(v[tab]||[]).map(x=>`<tr><td>${time(x.start_seconds)}</td><td>${esc(x.source)}</td><td>${esc(x.text)}</td></tr>`).join('')||'<tr><td colspan="3">目前沒有可顯示的文字；請確認影片檔與 OCR 執行狀態。</td></tr>'}
draw();</script></body></html>'''.replace('__DATA__',payload)
    dest=root/'site/video_recovery.html';dest.parent.mkdir(exist_ok=True);dest.write_text(page,encoding='utf8')
    print('已建立：',dest)


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--root',default='.')
    p.add_argument('--id',action='append')
    p.add_argument('--ocr',action='store_true')
    p.add_argument('--interval',type=float,default=1.)
    p.add_argument('--max-frames',type=int,default=2400)
    p.add_argument('--site-only',action='store_true')
    a=p.parse_args()
    if a.interval<.25 or a.max_frames<1:p.error('interval 至少 0.25 秒，max-frames 至少 1')
    if not a.site_only:run(a.root,set(a.id or []) or None,a.ocr,a.interval,a.max_frames)
    build_site(a.root)
if __name__=='__main__':main()
