"""觀音地方學：影片內容品質分析、選用 OCR、人工審核與過程事件紀錄。

不修改 crawler/video_extractor.py 或 output/index.jsonl；所有新輸出放在 output/video_quality。
命令：python -m crawler.video_quality analyze [--ocr --id extra_041]
      python -m crawler.video_quality review --id extra_041 --decision approve --note ...

OCR 是候選文字，不是已驗證文字；未審核資料禁止自動發布到知識庫。
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

MUSIC = re.compile(r'\[(?:music|singing|applause|instrumental|音樂|歌唱)[^\]]*\]|♪|♫|♬|\b(?:music|singing)\b', re.I)
CHINESE = re.compile(r'[\u4e00-\u9fff]')
ENGLISH = re.compile(r'[A-Za-z]')
SPACE = re.compile(r'\s+')


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (FileNotFoundError, json.JSONDecodeError, UnicodeError):
        return default


def save_json(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.tmp')
    temp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(path)


def seconds_text(n):
    n=max(0,int(float(n)))
    return f'{n//3600:02d}:{n//60%60:02d}:{n%60:02d}' if n>=3600 else f'{n//60:02d}:{n%60:02d}'


def video_id(url):
    p=urlparse(url or '')
    host=(p.hostname or '').lower().removeprefix('www.').removeprefix('m.')
    if host == 'youtu.be':
        candidate=p.path.strip('/').split('/')[0]
    elif host in ('youtube.com','youtube-nocookie.com'):
        parts=p.path.strip('/').split('/')
        candidate=parse_qs(p.query).get('v',[''])[0] if parts[0]=='watch' else parts[1] if len(parts)>1 and parts[0] in ('shorts','embed','live') else ''
    else:
        return ''
    return candidate if re.fullmatch(r'[A-Za-z0-9_-]{11}',candidate) else ''


def sources(root):
    file=root/'urls.csv'
    if not file.exists(): return []
    with file.open(encoding='utf-8-sig',newline='') as f:
        return [r for r in csv.DictReader(f) if r.get('type')=='video']


def find_record(root, source):
    """Prefer per-ID JSON so historical index records do not masquerade as current results."""
    f=root/'output/videos'/f'{source["id"]}.json'
    obj=read_json(f,None)
    if isinstance(obj,dict) and obj.get('type')=='video': return obj
    idx=root/'output/index.jsonl'
    if not idx.exists(): return None
    found=None
    for line in idx.read_text(encoding='utf-8-sig').splitlines():
        try: r=json.loads(line)
        except json.JSONDecodeError:continue
        if r.get('type')!='video':continue
        if r.get('id')==source['id'] or (video_id(r.get('source_url','')) and video_id(r.get('source_url',''))==video_id(source.get('url',''))):
            if found is None or r.get('crawled_at','') >= found.get('crawled_at',''): found=r
    return found


def norm(text):
    return SPACE.sub(' ',str(text or '').strip()).lower()


def subtitle_metrics(segments):
    texts=[str(s.get('text','')).strip() for s in segments if str(s.get('text','')).strip()]
    n=len(texts)
    if not n: return {'segments':0,'chinese_ratio':0.0,'english_ratio':0.0,'music_ratio':0.0,'duplicate_ratio':0.0,'very_short_ratio':0.0}
    normed=[norm(t) for t in texts]
    return {'segments':n,
            'chinese_ratio':round(sum(bool(CHINESE.search(t)) for t in texts)/n,3),
            'english_ratio':round(sum(bool(ENGLISH.search(t)) for t in texts)/n,3),
            'music_ratio':round(sum(bool(MUSIC.search(t)) for t in texts)/n,3),
            'duplicate_ratio':round(1-len(set(normed))/n,3),
            'very_short_ratio':round(sum(len(t)<=3 for t in texts)/n,3)}


def assess(record, mode_hint='auto'):
    if not record: return 'unprocessed','尚未取得影片紀錄',[]
    ts=record.get('timestamps') or []
    metrics=subtitle_metrics(ts)
    n=metrics['segments']
    evidence=[]
    status=str(record.get('crawl_status','')).lower()
    if status.startswith(('failed','error','失敗')):return 'failed','原始影片擷取失敗',[]
    if mode_hint == 'music_only':return 'visual_only','已由研究者指定：以影像為主，不採用歌曲字幕',[]
    if mode_hint == 'visual_only':return 'visual_only','已由研究者指定：無可靠語音逐字稿，應檢查畫面文字',[]
    if n == 0:return 'no_transcript','沒有可用語音字幕；可選擇執行 OCR',[]
    if metrics['english_ratio']>=.75 and metrics['chinese_ratio']<=.10:
        return 'suspected_music','英文字幕比例高且幾乎沒有中文，可能是歌曲／非地方解說',[]
    if metrics['music_ratio']>=.42:
        return 'suspected_music','字幕以音樂或歌唱標記為主',[]
    if metrics['duplicate_ratio']>=.40 or metrics['very_short_ratio']>=.42:
        evidence.append('大量重複或過短文字，應核對音軌')
    if mode_hint=='mixed_speech':evidence.append('研究者標記混合語言／客語，需人工核對')
    if 'whisper' in status:evidence.append('Whisper 自動轉錄未經人工核對')
    return 'needs_review','字幕已擷取，尚未通過內容審核',evidence


def candidate_subtitles(segments, quality_state):
    """保守清理候選文字；永遠不修改原始字幕，且未經審核不可作為事實。"""
    if quality_state in ('suspected_music', 'visual_only', 'failed', 'unprocessed'):
        return [], len(segments)
    rows=[]
    excluded=0
    for seg in segments:
        text=str(seg.get('text','')).strip()
        # 只排除純音樂／歌唱提示；不要任意刪除旁白中的英文地名。
        if not text or re.fullmatch(r'(?:\s*\[(?:music|singing|applause|instrumental|音樂|歌唱)[^\]]*\]\s*|[♪♫♬\s])+',text,re.I):
            excluded+=1
            continue
        if rows and norm(rows[-1].get('text'))==norm(text):
            try: gap=float(seg.get('start_seconds',0))-float(rows[-1].get('end_seconds',0))
            except (TypeError,ValueError):gap=999
            if gap<=2:
                rows[-1]['end_seconds']=seg.get('end_seconds',rows[-1].get('end_seconds'))
                rows[-1]['end']=seg.get('end',rows[-1].get('end'))
                excluded+=1
                continue
        rows.append(dict(seg,verified=False,source='subtitle_candidate'))
    return rows,excluded


def run_ocr(video_file: Path, every_seconds=2.0, max_frames=600):
    """Optional OCR. Frames are sampled; OCR text is evidence candidate only."""
    try:
        import cv2
        from rapidocr_onnxruntime import RapidOCR
    except ImportError as e:
        raise RuntimeError('OCR 需要安裝：py -3.12 -m pip install rapidocr-onnxruntime opencv-python') from e
    cap=cv2.VideoCapture(str(video_file))
    if not cap.isOpened():raise RuntimeError(f'影片無法開啟：{video_file}')
    fps=float(cap.get(cv2.CAP_PROP_FPS) or 25)
    frames=int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    duration=frames/fps if fps else 0
    cap.release()
    if duration <= 0:raise RuntimeError('無法讀取影片長度')
    ocr=RapidOCR()
    rows=[]
    for idx in range(min(max_frames,int(duration/every_seconds)+1)):
        at=round(idx*every_seconds,2)
        if at >= duration:break
        cap=cv2.VideoCapture(str(video_file)) if idx==0 else cap
        # Keep one capture open for subsequent seeks
        cap.set(cv2.CAP_PROP_POS_MSEC,at*1000)
        ok,frame=cap.read()
        if not ok: continue
        # Scale to limit OCR inference overhead; maintain original timestamps.
        h,w=frame.shape[:2]
        if w>1280:frame=cv2.resize(frame,(1280,int(h*1280/w)))
        result,_=ocr(frame)
        for box,text,score in result or []:
            clean=SPACE.sub(' ',str(text)).strip()
            if not clean or float(score)<.55 or len(clean)<2:continue
            if rows and norm(rows[-1]['text'])==norm(clean) and at-rows[-1]['end_seconds']<=every_seconds+0.5:
                rows[-1]['end_seconds']=at+every_seconds
                rows[-1]['end']=seconds_text(at+every_seconds)
                continue
            rows.append({'start':seconds_text(at),'end':seconds_text(at+every_seconds),
                         'start_seconds':at,'end_seconds':round(at+every_seconds,2),
                         'text':clean,'confidence':round(float(score),3),
                         'source':'ocr_candidate','verified':False})
    if 'cap' in locals():cap.release()
    return rows


def locate_media(root,source):
    vid=video_id(source.get('url',''))
    dirs=[root/'downloads'/vid,root/'output/downloads'/vid]
    for d in dirs:
        for ext in ('*.mp4','*.mkv','*.webm'):
            matches=sorted(d.glob(ext)) if d.is_dir() else []
            if matches:return matches[0]
    return None


def stages(record, mode, ocr_attempted, ocr_count, ocr_error):
    """Stages describe known workflow evidence, NOT invented execution timestamps or elapsed durations."""
    if not record:
        return [dict(step=x,status='pending',detail='尚未取得此階段結果',time=None) for x in ('來源註冊','影片取得','語音字幕','影格擷取','OCR','品質評估','人工審核')]
    subtitle=str(record.get('crawl_status',''))
    has_frames=bool(record.get('images'))
    has_text=bool(record.get('timestamps'))
    if 'youtube_vtt' in subtitle: method='YouTube VTT'
    elif 'whisper' in subtitle: method='Whisper'
    else:method='沒有可用語音逐字稿'
    return [
        dict(step='來源註冊',status='done',detail='有影片來源 ID 與原始網址',time=None),
        dict(step='影片取得',status='done' if str(record.get('crawl_status','')).startswith('success') else 'failed',detail='來源影片資訊已輸出（不代表授權已確認）',time=None),
        dict(step='語音字幕',status='done' if has_text else 'skipped',detail=f'{method}；{len(record.get("timestamps") or [])} 段原始字幕',time=None),
        dict(step='代表畫面',status='done' if has_frames else 'skipped',detail=f'{len(record.get("images") or [])} 張影格',time=None),
        dict(step='畫面文字 OCR',status='failed' if ocr_error else 'done' if ocr_attempted else 'pending',detail=f'{ocr_count} 段候選畫面文字' if ocr_attempted and not ocr_error else (ocr_error or '尚未執行，可使用 --ocr'),time=None),
        dict(step='字幕品質分析',status='done',detail=f'判定：{mode}；屬自動初篩',time=None),
        dict(step='人工審核',status='pending',detail='需人工比對影音、地名與引用來源',time=None),
    ]


def analyze(root='.', ids=None, do_ocr=False, every_seconds=2.0, max_frames=600):
    root=Path(root)
    out=root/'output/video_quality'
    out.mkdir(parents=True,exist_ok=True)
    rules=read_json(root/'data/video_quality_rules.json',{})
    summary=[]
    for src in sources(root):
        sid=src['id']
        if ids and sid not in ids:continue
        original=find_record(root,src)
        hint=rules.get(sid,{}).get('mode','auto')
        state,reason,flags=assess(original,hint)
        raw_subs=(original or {}).get('timestamps') or []
        metrics=subtitle_metrics(raw_subs)
        candidates,excluded_count=candidate_subtitles(raw_subs,state)
        old=read_json(out/f'{sid}.json',{})
        ocr_rows=old.get('ocr_texts',[])
        ocr_attempted=bool(old.get('ocr_attempted',False))
        ocr_error=''
        if do_ocr:
            media=locate_media(root,src)
            ocr_attempted=True
            if media:
                try:ocr_rows=run_ocr(media,every_seconds,max_frames)
                except Exception as e:ocr_error=str(e)
            else:ocr_error='找不到本機影片檔：請確認 downloads/<YouTube ID>/*.mp4'
        manual=read_json(out/'reviews'/f'{sid}.json',{})
        review_state=manual.get('decision','pending')
        workflow=stages(original,state,ocr_attempted,len(ocr_rows),ocr_error)
        workflow[-1]['status']='done' if review_state in ('approved','rejected') else 'pending'
        workflow[-1]['detail']=f'{review_state}：{manual.get("note", "")} ' if manual else '尚未人工審核'
        rec={'id':sid,'video_id':video_id(src.get('url','')),'source_url':src.get('url',''),
             'title':(original or {}).get('title') or src.get('title_hint') or sid,
             'raw_crawl_status':(original or {}).get('crawl_status','unprocessed'),
             'subtitle_source': 'youtube_vtt' if 'youtube_vtt' in str((original or {}).get('crawl_status','')) else ('whisper' if 'whisper' in str((original or {}).get('crawl_status','')) else 'none'),
             'raw_subtitle_count':metrics['segments'],'candidate_subtitle_count':len(candidates),
             'excluded_subtitle_count':excluded_count,'candidate_timestamps':candidates,
             'image_count':len((original or {}).get('images') or []),
             'metrics':metrics,'quality_state':state,'quality_reason':reason,'warnings':flags,
             'ocr_attempted':ocr_attempted,'ocr_error':ocr_error,'ocr_texts':ocr_rows,
             'review_state':review_state,'review_note':manual.get('note',''),
             'reviewed_at':manual.get('reviewed_at'),
             'stages':workflow,'analyzed_at':utc_now(),
             'crawled_at':(original or {}).get('crawled_at'),
             'images':(original or {}).get('images') or [],
             'raw_timestamps':(original or {}).get('timestamps') or [],
             'usable_for_knowledge':review_state=='approved' and state not in ('suspected_music','visual_only','failed','unprocessed')}
        save_json(out/f'{sid}.json',rec)
        summary.append({k:v for k,v in rec.items() if k not in ('ocr_texts','images','raw_timestamps','candidate_timestamps','stages')})
        print(f'{sid:11} | {state:17} | {metrics["segments"]:4} 字幕 | {len(ocr_rows):4} OCR | 審核 {review_state}')
    save_json(out/'summary.json',summary)
    print(f'品質分析完成：{len(summary)} 部影片；原始影片 JSON 和 index.jsonl 均未修改。')
    return summary


def review(root,id,decision,note):
    root=Path(root)
    if not any(s['id']==id for s in sources(root)):raise ValueError('網址清單找不到指定影片 ID')
    if decision=='approved' and not note.strip():raise ValueError('核准時必須提供人工核對內容及來源說明 --note')
    file=root/'output/video_quality/reviews'/f'{id}.json'
    save_json(file,dict(id=id,decision=decision,note=note.strip(),reviewed_at=utc_now()))
    print('已記錄人工審核：',id,decision,'；請重新執行 analyze 以更新網頁資料')


def main():
    p=argparse.ArgumentParser(description='觀音影片品質分析、OCR 與人工審核（保留原始結果）')
    p.add_argument('action',choices=['analyze','review'],nargs='?',default='analyze')
    p.add_argument('--root',default='.')
    p.add_argument('--id',action='append',help='單一或多個來源 ID，可重複指定')
    p.add_argument('--ocr',action='store_true',help='選用：對本機影片進行畫面文字 OCR')
    p.add_argument('--interval',type=float,default=2.0,help='OCR 抽影格間隔（秒）')
    p.add_argument('--max-frames',type=int,default=600,help='OCR 最大抽影格數')
    p.add_argument('--decision',choices=['approved','rejected','pending'])
    p.add_argument('--note',default='')
    a=p.parse_args()
    if a.action=='review':
        if len(a.id or [])!=1 or not a.decision:p.error('review 需要 --id 指定一部影片及 --decision')
        review(a.root,a.id[0],a.decision,a.note)
    else:
        if a.interval<0.25 or a.max_frames<1:p.error('--interval 至少 0.25 秒，--max-frames 至少 1')
        analyze(a.root,set(a.id) if a.id else None,a.ocr,a.interval,a.max_frames)

if __name__=='__main__':main()
