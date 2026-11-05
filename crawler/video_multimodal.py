"""觀音地方學：音訊類型、CC/Whisper、畫面文字、選用翻譯之第二階段處理。

不修改原始 output/videos/*.json 或 output/index.jsonl。
只新增 output/video_multimodal/*.json；人工確認由原有 video_quality review 流程保存。
音訊分類需選擇 --audio；沒有聲音模型時不會假稱已分析聲音。
"""
from __future__ import annotations
import argparse
import json
import re
import subprocess
import tempfile
from pathlib import Path
from datetime import datetime, timezone
from difflib import SequenceMatcher
from .video_quality import (sources, find_record, locate_media, read_json, save_json,
                            subtitle_metrics, norm, video_id, seconds_text)

RE_MUSIC = re.compile(r"\[(music|singing|instrumental|音樂|歌唱|applause)[^\]]*\]|[♪♫♬]",re.I)
RE_ZH = re.compile(r'[\u4e00-\u9fff]')
RE_LATIN = re.compile(r'[A-Za-z]')


def audio_classify(media:Path):
    """使用真正的預訓練 speech/music/noise segmentation；無套件或失敗則報錯、不假裝完成。"""
    try: from inaSpeechSegmenter import Segmenter
    except ImportError as exc:
        raise RuntimeError('請先安裝音訊分類：py -3.12 -m pip install inaSpeechSegmenter') from exc
    try: import imageio_ffmpeg
    except ImportError as exc:
        raise RuntimeError('缺少 imageio-ffmpeg') from exc
    with tempfile.TemporaryDirectory(prefix='guanyin_audio_') as tmp:
        wav=Path(tmp)/'audio.wav'
        cmd=[imageio_ffmpeg.get_ffmpeg_exe(),'-hide_banner','-loglevel','error','-y','-i',str(media),'-vn',
             '-ac','1','-ar','16000','-c:a','pcm_s16le',str(wav)]
        p=subprocess.run(cmd,capture_output=True,text=True,timeout=1200)
        if p.returncode!=0: raise RuntimeError('ffmpeg 音訊抽取失敗：'+p.stderr[-450:])
        segmenter=Segmenter(vad_engine='smn',detect_gender=False)
        spans=[]
        for lab,start,end in segmenter(str(wav)):
            label={'speech':'speech','music':'music','noise':'noise','noEnergy':'silence'}.get(lab,lab)
            spans.append({'type':label,'start_seconds':round(float(start),2),'end_seconds':round(float(end),2)})
        return spans


def extract_ocr(media:Path,interval:float=2.0,max_frames:int=1000,minimum_score:float=.65):
    """OCR 不只抽 4 張封面；同一位置連續的相似文字合併，保留出現時間。"""
    try:
        import cv2
        from rapidocr_onnxruntime import RapidOCR
    except ImportError as exc:
        raise RuntimeError('請安裝 OCR：py -3.12 -m pip install rapidocr-onnxruntime opencv-python') from exc
    cap=cv2.VideoCapture(str(media))
    if not cap.isOpened():raise RuntimeError('無法開啟影片：'+str(media))
    fps=cap.get(cv2.CAP_PROP_FPS) or 25
    frames=cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
    length=frames/fps if fps>0 else 0
    if length<=0:
        cap.release();raise RuntimeError('無法讀取影片長度')
    engine=RapidOCR()
    # 同一時間可能有多行，依畫面位置追蹤，而不是只與最後一行比較。
    found=[];active={}
    try:
        for i in range(min(max_frames,int(length/interval)+1)):
            t=round(i*interval,2)
            if t>=length:break
            cap.set(cv2.CAP_PROP_POS_MSEC,t*1000)
            ok,frame=cap.read()
            if not ok:continue
            h,w=frame.shape[:2]
            if w>1280:frame=cv2.resize(frame,(1280,max(1,round(1280*h/w))))
            res,_=engine(frame)
            # 畫面文字可能是浮水印；先全部留下位置與信心，供後續挑選。
            for item in (res or []):
                if len(item)<3:continue
                box,raw,score=item[:3]
                txt=' '.join(str(raw).split())
                if len(txt)<2 or float(score)<minimum_score:continue
                xs=[float(p[0]) for p in box];ys=[float(p[1]) for p in box]
                x=round(sum(xs)/len(xs),1);y=round(sum(ys)/len(ys),1)
                key=(round(x/70),round(y/40))
                best=None
                for prior in active.get(key,[]):
                    if t-prior['last_seen']<=interval*1.6 and SequenceMatcher(None,norm(txt),norm(prior['text'])).ratio()>=.82:
                        best=prior;break
                if best:
                    best['last_seen']=t
                    best['end_seconds']=round(min(length,t+interval),2)
                    best['confidence']=round(max(best['confidence'],float(score)),3)
                else:
                    rec={'start_seconds':t,'end_seconds':round(min(length,t+interval),2),
                         'last_seen':t,'text':txt,'confidence':round(float(score),3),'position':[x,y],
                         'source':'ocr','verified':False}
                    found.append(rec)
                    active.setdefault(key,[]).append(rec)
            # 防止無限保留舊文字狀態
            for key in list(active):
                active[key]=[z for z in active[key] if t-z['last_seen']<=interval*1.6]
                if not active[key]:del active[key]
    finally:cap.release()
    for r in found:
        r.pop('last_seen',None)
        r['start']=seconds_text(r['start_seconds']);r['end']=seconds_text(r['end_seconds'])
    return sorted(found,key=lambda z:(z['start_seconds'],z['position'][1]))


def music_overlap(segment,audio):
    """只在模型明確為 music 的區段加註；音樂伴隨旁白的區段不自動丟棄。"""
    a=float(segment.get('start_seconds') or 0)
    b=float(segment.get('end_seconds') or a+1)
    if b<=a:b=a+1
    dur=b-a
    cover=0.0
    for s in audio:
        if s.get('type')!='music':continue
        cover+=max(0,min(b,s['end_seconds'])-max(a,s['start_seconds']))
    return min(1.0,cover/dur)


def select_subtitles(record,audio=None,manual_mode='auto'):
    """拒絕把明顯配樂字幕當地方介紹；其他內容作候選且保留來源。"""
    raw=record.get('timestamps') or []
    src='youtube_cc' if 'youtube_vtt' in str(record.get('crawl_status','')) else 'whisper' if 'whisper' in str(record.get('crawl_status','')) else 'none'
    stats=subtitle_metrics(raw)
    global_music=(stats['english_ratio']>=.75 and stats['chinese_ratio']<=.10 and
                  (stats['music_ratio']>=.12 or stats['duplicate_ratio']>=.25))
    global_music=global_music or manual_mode=='music_only'
    selected=[];rejected=[]
    for x in raw:
        r=dict(x,source=src,verified=False)
        t=str(r.get('text','')).strip()
        if not t:continue
        overlap=music_overlap(r,audio or []) if audio is not None else None
        reason=None
        if RE_MUSIC.fullmatch(t):reason='music_marker'
        elif global_music:reason='music_or_lyrics'
        elif overlap is not None and overlap>=.85 and not RE_ZH.search(t):reason='music_window'
        if reason:
            r['exclude_reason']=reason;rejected.append(r)
        else:selected.append(r)
    return src,selected,rejected,stats


def translate_english(rows,enabled=False,max_items=300):
    """選用本機模型，只有英語敘述才翻譯；不下載則不聲稱已翻譯。"""
    if not enabled:return [],'not_requested'
    eligible=[r for r in rows if RE_LATIN.search(str(r.get('text',''))) and not RE_ZH.search(str(r.get('text',''))) and not RE_MUSIC.search(str(r.get('text','')))][:max_items]
    if not eligible:return [],'no_english_narration'
    try:
        from transformers import pipeline
        from opencc import OpenCC
        trans=pipeline('translation',model='Helsinki-NLP/opus-mt-en-zh')
        cc=OpenCC('s2twp')
        translated=[]
        for i in range(0,len(eligible),8):
            batch=eligible[i:i+8]
            output=trans([x['text'] for x in batch],max_length=256)
            for row,t in zip(batch,output):
                translated.append({'start_seconds':row.get('start_seconds',0),
                    'end_seconds':row.get('end_seconds',0),'original':row['text'],
                    'text':cc.convert(t['translation_text']),'source':'translation',
                    'model':'Helsinki-NLP/opus-mt-en-zh','verified':False})
        return translated,'done'
    except Exception as exc:
        return [],'failed: '+str(exc)[:400]


def apply_manual_corrections(segments, correction_rows):
    """只套用研究者明確提供的修正；絕不由模型自行補造地方史實。

    修正鍵：source (youtube_cc/whisper/ocr)、start_seconds、text、note。
    時間容許 0.5 秒，避免字幕毫秒四捨五入造成無法比對。
    """
    result=[];applied=0
    for raw in segments:
        row=dict(raw)
        for fix in correction_rows:
            if (fix.get('source')==row.get('source') and
                abs(float(fix.get('start_seconds',-9999))-float(row.get('start_seconds',0)))<=.5 and
                str(fix.get('text','')).strip()):
                row['original_text']=row.get('text','')
                row['text']=str(fix['text']).strip()
                row['correction_note']=str(fix.get('note',''))
                row['corrected_by_reviewer']=True
                applied+=1
                break
        result.append(row)
    return result,applied


def topic_keywords(text):
    lex={'地理與自然環境':['大堀溪','大崛溪','埤塘','水文','河川','沙丘','地形'],
         '地方歷史與聚落發展':['石門水庫','遷村','移民新村','石觀音','日治','古厝'],
         '族群信仰與民俗':['客家','海客','甘泉寺','民俗','宮廟'],
         '農業與鄉村生活':['蓮花','蓮荷','農場','農業','稻田'],
         '海岸生態與環境保育':['藻礁','保育','海岸','沙丘'],
         '工業與能源發展':['電廠','工業區','能源','風力發電'],
         '地方文化與生活記憶':['燈塔','生活記憶','文化地景','龜殼劇場'],
         '當代議題與地方未來':['永續','領海基點','海洋法制']}
    return [k for k,words in lex.items() if any(w in text for w in words)]


def analyze(root='.',ids=None,with_audio=False,with_ocr=False,translate=False,interval=2.0,max_frames=1000):
    root=Path(root); out=root/'output/video_multimodal';out.mkdir(parents=True,exist_ok=True)
    rules=read_json(root/'data/video_quality_rules.json',{})
    report=[]
    for source in sources(root):
        sid=source['id']
        if ids and sid not in ids:continue
        original=find_record(root,source)
        if original is None:
            print(sid,'沒有原始影片成果，略過');continue
        media=locate_media(root,source)
        old=read_json(out/f'{sid}.json',{})
        log=[]
        def event(name,status,info):
            log.append({'name':name,'status':status,'detail':str(info),'recorded_at':datetime.now(timezone.utc).isoformat(timespec='seconds')})
        event('讀取影片來源','done',original.get('title',sid))
        if with_audio:
            if media:
                try:audio=audio_classify(media);audio_status='done';event('聲音分類','done',f'{len(audio)} 區段')
                except Exception as e:audio=[];audio_status='failed: '+str(e);event('聲音分類','failed',str(e))
            else:audio=[];audio_status='missing_media';event('聲音分類','skipped','找不到本機影片')
        else:
            audio=old.get('audio_segments',[]);audio_status=old.get('audio_status','not_run');event('聲音分類','done' if audio_status=='done' else 'skipped',audio_status)
        hint=rules.get(sid,{}).get('mode','auto')
        src,chosen,discarded,metrics=select_subtitles(original,audio if audio_status=='done' else None,hint)
        event('CC／語音字幕整理','done',f'{src}：保留 {len(chosen)} 段；隔離 {len(discarded)} 段')
        if with_ocr:
            if media:
                try:ocr=extract_ocr(media,interval,max_frames);ocr_status='done';event('畫面 OCR','done',f'{len(ocr)} 段候選文字')
                except Exception as e:ocr=[];ocr_status='failed: '+str(e);event('畫面 OCR','failed',str(e))
            else:ocr=[];ocr_status='missing_media';event('畫面 OCR','skipped','找不到本機影片')
        else:
            ocr=old.get('ocr_segments',[]);ocr_status=old.get('ocr_status','not_run');event('畫面 OCR','done' if ocr_status=='done' else 'skipped',ocr_status)
        fixes=read_json(root/'data/video_corrections.json',{}).get(sid,[])
        chosen,cc_fixes=apply_manual_corrections(chosen,fixes)
        ocr,ocr_fixes=apply_manual_corrections(ocr,fixes)
        event('人工文字修正','done' if cc_fixes+ocr_fixes else 'skipped',f'依修正清單套用 {cc_fixes+ocr_fixes} 處')
        translated,translation_status=translate_english(chosen,translate)
        if not translate and old.get('translation_status')=='done':
            translated=old.get('translations',[]);translation_status='done'
        event('選擇性翻譯','done' if translation_status=='done' else 'skipped',translation_status)
        review=read_json(root/'output/video_quality/reviews'/f'{sid}.json',{})
        # 審查決議在內部保存；公開頁僅顯示已產生的內容與資料來源，不顯示指定標籤。
        event('交叉整合','done','保留來源、時間戳記與不同文字來源；自動分類不等於史料查證')
        rec={'id':sid,'title':original.get('title') or sid,'source_url':source.get('url'),
             'video_id':video_id(source.get('url')),'duration':(original.get('metadata') or {}).get('duration'),
             'raw_status':original.get('crawl_status'),'subtitle_source':src,'metrics':metrics,
             'audio_status':audio_status,'audio_segments':audio,
             'subtitle_segments':chosen,'excluded_subtitles':discarded,
             'ocr_status':ocr_status,'ocr_segments':ocr,'translation_status':translation_status,'translations':translated,
             'images':original.get('images') or [],'topics':topic_keywords(' '.join(r.get('text','') for r in chosen+ocr)),
             'review':review,'events':log,'generated_at':datetime.now(timezone.utc).isoformat(timespec='seconds')}
        save_json(out/f'{sid}.json',rec)
        report.append({'id':sid,'audio':audio_status,'ocr':ocr_status,'cc':len(chosen),'excluded':len(discarded),'ocr_count':len(ocr)})
        print(f'{sid:11} | 字幕 {len(chosen):4} | 排除 {len(discarded):4} | OCR {len(ocr):4} | 音訊 {audio_status}')
    save_json(out/'summary.json',report)
    return report


def main():
    p=argparse.ArgumentParser(description='觀音地方學影音第二階段：聲音分類／字幕／OCR／翻譯／整合')
    p.add_argument('--root',default='.');p.add_argument('--id',action='append')
    p.add_argument('--audio',action='store_true',help='實際使用 inaSpeechSegmenter 執行聲音分類')
    p.add_argument('--ocr',action='store_true',help='實際使用 RapidOCR 執行畫面文字辨識')
    p.add_argument('--translate',action='store_true',help='選用 transformers 英譯中模型，模型初次使用需下載')
    p.add_argument('--interval',type=float,default=2.0);p.add_argument('--max-frames',type=int,default=1000)
    a=p.parse_args()
    if a.interval<.5 or a.max_frames<1:p.error('--interval 至少 0.5 秒，--max-frames 至少 1')
    analyze(a.root,set(a.id or []) or None,a.audio,a.ocr,a.translate,a.interval,a.max_frames)

if __name__=='__main__':main()
