"""Synchronize video records into the generated source dashboard without changing teammate code.

Run AFTER crawler.build_site and crawler.video_site. Edits only site/index.html.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

VIDEO_RE = re.compile(r'^[\w-]{11}$')
START = '<!-- GUANYIN_VIDEO_SYNC_START -->'
END = '<!-- GUANYIN_VIDEO_SYNC_END -->'


def video_id(url):
    try:
        p = urlparse(url)
        host = (p.hostname or '').lower().removeprefix('www.').removeprefix('m.')
        if host == 'youtu.be':
            vid = p.path.strip('/').split('/')[0]
        elif host in ('youtube.com', 'youtube-nocookie.com'):
            parts = p.path.strip('/').split('/')
            vid = parse_qs(p.query).get('v', [''])[0] if parts[0] == 'watch' else parts[1] if len(parts)>1 and parts[0] in ('shorts','embed','live') else ''
        else: return ''
        return vid if VIDEO_RE.fullmatch(vid) else ''
    except (IndexError, TypeError): return ''


def read_records(index, videos):
    records = {}
    files = [*sorted(Path(videos).glob('*.json'))] if Path(videos).exists() else []
    for path in files:
        try:
            obj = json.loads(path.read_text(encoding='utf-8'))
            if isinstance(obj,dict) and obj.get('type') == 'video':
                vid = video_id(obj.get('source_url','')) or str(obj.get('metadata',{}).get('video_id',''))
                if vid: records[vid] = obj
        except (OSError,ValueError): pass
    if Path(index).exists():
        for line in Path(index).read_text(encoding='utf-8').splitlines():
            try:
                obj = json.loads(line)
                if obj.get('type') != 'video':continue
                vid = video_id(obj.get('source_url','')) or str(obj.get('metadata',{}).get('video_id',''))
                if vid:
                    current = records.get(vid)
                    if current is None or obj.get('crawled_at','') > current.get('crawled_at',''):
                        records[vid] = obj
            except (ValueError,AttributeError):continue
    return records


def summarise(record):
    if not record:return {'state':'unprocessed','subtitles':0,'images':0,'reason':'尚無影片成果紀錄'}
    subs = len(record.get('timestamps') or [])
    images = len(record.get('images') or [])
    status = str(record.get('crawl_status','')).lower()
    if status.startswith(('failed','error','失敗')):
        state = 'failed'
    elif subs and images:
        state = 'complete'
    elif subs or images:
        state = 'partial'
    elif 'success' in status or 'ok' in status:
        state = 'partial'
    else:
        state = 'unprocessed'
    reason = f'{subs} 段字幕、{images} 張代表畫面'
    if state=='failed':reason += '；' + str(record.get('crawl_status',''))[:140]
    if state=='partial' and subs==0:reason += '；字幕尚未取得'
    if state=='partial' and images==0:reason += '；代表畫面尚未取得'
    return {'state':state,'subtitles':subs,'images':images,'reason':reason}


def update(html_path, index_path, videos_dir):
    path = Path(html_path)
    html = path.read_text(encoding='utf-8')
    if START in html:
        raise RuntimeError("首頁已同步過影片結果；請先執行 python -m crawler.build_site 再重新同步")
    source = re.search(r'const data=(\[.*?\]);\s*const el=', html, re.S)
    if not source:
        raise RuntimeError('找不到原有網頁來源清單：請先執行 python -m crawler.build_site')
    rows = json.loads(source.group(1))
    records = read_records(index_path, videos_dir)
    mapping={}
    for row in rows:
        if row.get('type') != 'video':continue
        vid=video_id(row.get('url',''))
        mapping[row['id']]=summarise(records.get(vid))
    # Inject data mapping before kind/label; existing filtering, search & rendering continue to work.
    script = '''const VIDEO_SYNC_DATA=__JSON__;
for (const x of data) {
 const v=VIDEO_SYNC_DATA[x.id];
 if(v){x.video_state=v.state;x.filter_reason=v.reason;x.last_http_status='';}
}
'''.replace('__JSON__', json.dumps(mapping,ensure_ascii=False).replace('<','\\u003c').replace('&','\\u0026'))
    if 'const kind=x=>' not in html or 'const label=x=>' not in html:
        raise RuntimeError('目前首頁 JavaScript 結構不同，未執行修改，避免破壞網站。')
    html=html.replace('const kind=x=>', START + '\n' + script + '\nconst kind=x=>x.video_state ? ({complete:"video_complete",partial:"video_partial",failed:"video_failed",unprocessed:"video_unprocessed"}[x.video_state]||"video_unprocessed") : ',1)
    html=html.replace('const label=x=>', 'const label=x=>x.video_state ? ({complete:"影片完成（字幕＋畫面）",partial:"影片部分完成",failed:"影片處理失敗",unprocessed:"影片尚無成果"}[x.video_state]||"影片待確認") : ',1)
    html=html.replace("+rows('暫時排除',count('excluded'));", "+rows('暫時排除',count('excluded'))+rows('影片完整成果',count('video_complete'))+rows('影片部分成果',count('video_partial'))+rows('影片尚待處理',count('video_failed')+count('video_unprocessed'));",1)
    html=html.replace('<option value="not_audited">尚未產生審核報告</option>', '<option value="not_audited">尚未產生審核報告</option><option value="video_complete">影片完整成果</option><option value="video_partial">影片部分成果</option><option value="video_failed">影片處理失敗</option><option value="video_unprocessed">影片尚無成果</option>', 1)
    html=html.replace('</style>', '''.badge.video_complete{background:#e5f2ec;color:#246e57}.badge.video_partial{background:#fff0d8;color:#865a14}.badge.video_failed{background:#f8e9e7;color:#9d4a43}.badge.video_unprocessed{background:#eeeef2;color:#575466}</style>''',1)
    html=html.replace('</body>', END+'\n</body>',1)
    path.write_text(html,encoding='utf-8')
    print('首頁已同步影片狀態：',path)
    for sid,v in mapping.items():print(f"  {sid}: {v['state']}，{v['subtitles']} 段字幕／{v['images']} 張圖")
    return mapping


def main():
    p=argparse.ArgumentParser(description='同步影片字幕與圖片結果到來源管理首頁')
    p.add_argument('--html',default='site/index.html')
    p.add_argument('--index',default='output/index.jsonl')
    p.add_argument('--videos',default='output/videos')
    a=p.parse_args()
    update(a.html,a.index,a.videos)

if __name__=='__main__':main()
