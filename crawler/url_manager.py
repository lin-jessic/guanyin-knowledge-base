import csv
import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

FIELDS = ['id', 'url', 'type', 'origin', 'title_hint', 'topic', 'publisher', 'enabled', 'notes', 'geo_scope', 'source_role', 'review_status', 'evidence', 'verified_at']
TRACKING = {'si','guccounter','guce_referrer','guce_referrer_sig','fbclid','gclid'}

def canonical(url):
    u = urlsplit(url.strip())
    query = urlencode(sorted((k,v) for k,v in parse_qsl(u.query,keep_blank_values=True) if k.lower() not in TRACKING and not k.lower().startswith('utm_')))
    return urlunsplit((u.scheme.lower(),u.netloc.lower(),u.path or '/',query,''))

def valid_url(url):
    try:
        u=urlsplit(url.strip())
        return u.scheme.lower() in {'http','https'} and bool(u.hostname) and not (u.username or u.password) and not re.search(r'\s',url)
    except ValueError:
        return False

def is_video(url):
    return (urlsplit(url).hostname or '').lower() in {'youtu.be','youtube.com','www.youtube.com','m.youtube.com'}

def read_rows(path):
    p=Path(path)
    with p.open(encoding='utf-8-sig',newline='') as f:
        rows=list(csv.DictReader(f))
    for r in rows:
        r.setdefault('origin','teacher')
        r.setdefault('enabled','true')
        for field in FIELDS:r.setdefault(field,'')
        if not r['type']:r['type']='video' if is_video(r['url']) else 'web'
    return rows

def write_rows(path,rows):
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
    if p.exists():
        backup=p.with_name(f'{p.stem}.backup_{datetime.now().strftime("%Y%m%d_%H%M%S_%f")}{p.suffix}')
        shutil.copy2(p,backup)
    temp=p.with_name(p.name+'.tmp')
    with temp.open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,FIELDS,extrasaction='ignore');writer.writeheader();writer.writerows(rows)
    os.replace(temp,p)

def load_urls(path,include_disabled=False):
    found=[];seen=set()
    for r in read_rows(path):
        if not include_disabled and r.get('enabled','true').lower() in ('false','0','no'):continue
        if not valid_url(r['url']):continue
        key=canonical(r['url'])
        if key in seen:continue
        seen.add(key);r['type']='video' if is_video(r['url']) else 'web';found.append(r)
    return found

def add_url(path,url,title='',topic='',publisher='',notes=''):
    if not valid_url(url):raise ValueError('網址必須是有效的 http(s) URL')
    rows=read_rows(path)
    if any(canonical(r['url'])==canonical(url) for r in rows):raise ValueError('網址已存在，請使用 update 或 enable')
    ids=[int(r['id'].split('_')[-1]) for r in rows if re.fullmatch(r'extra_\d+',r['id'])]
    ident=f'extra_{max(ids,default=0)+1:03d}'
    rows.append(dict(id=ident,url=url,type='video' if is_video(url) else 'web',origin='extra',title_hint=title,topic=topic,publisher=publisher,enabled='true',notes=notes,geo_scope='pending_review',source_role='content',review_status='unreviewed',evidence='使用者新增，未查核',verified_at=''))
    write_rows(path,rows);return ident

def update_url(path,ident,**changes):
    rows=read_rows(path);target=next((r for r in rows if r['id']==ident),None)
    if not target:raise ValueError('找不到指定 ID')
    if 'url' in changes and changes['url']!=target['url']:
        if target['origin']=='teacher':raise ValueError('教師原始網址不可改動；可停用後另新增 extra 網址')
        if not valid_url(changes['url']):raise ValueError('網址格式錯誤')
        if any(r['id']!=ident and canonical(r['url'])==canonical(changes['url']) for r in rows):raise ValueError('與現有網址重複')
        changes['type']='video' if is_video(changes['url']) else 'web'
    target.update(changes)
    write_rows(path,rows)

def delete_url(path,ident):
    rows=read_rows(path);target=next((r for r in rows if r['id']==ident),None)
    if not target:raise ValueError('找不到指定 ID')
    if target['origin']=='teacher':raise ValueError('教師指定網址不能永久刪除；請使用 disable 保留驗收紀錄')
    write_rows(path,[r for r in rows if r['id']!=ident])
