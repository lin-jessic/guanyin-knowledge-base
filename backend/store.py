"""Read existing team output without modifying its source data."""
import csv,json,re,sqlite3
from pathlib import Path
from datetime import datetime,timezone
from .content import TOPIC_MAP,FEATURES

ROOT=Path(__file__).resolve().parents[1]
DB=ROOT/'storage'/'guanyin_public.db'

def connect():
    DB.parent.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(DB)
    db.row_factory=sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    db.execute('PRAGMA busy_timeout=5000')
    return db

def init():
    with connect() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS sources(id TEXT PRIMARY KEY,type TEXT,title TEXT,url TEXT,source_name TEXT,topic TEXT,raw_status TEXT,content TEXT,image_json TEXT,video_json TEXT,updated_at TEXT);
        CREATE TABLE IF NOT EXISTS features(slug TEXT PRIMARY KEY, topic TEXT,title TEXT,lead TEXT,questions TEXT,method TEXT,claims TEXT,tags TEXT,status TEXT,editor_body TEXT DEFAULT '',publication TEXT DEFAULT 'draft',updated_at TEXT);
        CREATE TABLE IF NOT EXISTS review_log(id INTEGER PRIMARY KEY AUTOINCREMENT,slug TEXT,action TEXT,note TEXT,created_at TEXT);
        CREATE TABLE IF NOT EXISTS media_rights(path TEXT PRIMARY KEY,allow_public INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS places(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,topic TEXT,latitude REAL,longitude REAL,source_url TEXT,reviewed INTEGER NOT NULL DEFAULT 0);
        ''')
        for f in FEATURES:
            db.execute('''INSERT OR IGNORE INTO features(slug,topic,title,lead,questions,method,claims,tags,status,updated_at)
             VALUES(?,?,?,?,?,?,?,?,?,?)''',(f['slug'],f['topic'],f['title'],f['lead'],json.dumps(f['questions'],ensure_ascii=False),f['method'],json.dumps(f['claim_ids'],ensure_ascii=False),json.dumps(f['tags'],ensure_ascii=False),f['status'],stamp()))

def stamp():return datetime.now(timezone.utc).isoformat(timespec='seconds')

def read_json(path):
    try:return json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError,ValueError):return None

def safe_excerpt(s,n=260):
    """Avoid publishing scraped JavaScript/long verbatim text; short source pointers only."""
    s=re.sub(r'<[^>]+>',' ',str(s or ''))
    s=re.sub(r'(?m)^.*(?:\$\(|document\.|querySelector|function\s*\(|\.addEventListener|javascript:|window\.|console\.|\bvar\s+\w+\s*=).*$', ' ',s)
    s=re.sub(r'\[[^\]]+\]\([^)]*\)',' ',s)
    s=re.sub(r'[`{};]+',' ',s)
    s=re.sub(r'\s+',' ',s).strip()
    return s[:n] + ('…' if len(s)>n else '')

def import_outputs():
    """Idempotent reimport: updates source snapshots, never resets human editorial decisions."""
    init()
    idx=ROOT/'output/index.jsonl'
    found={}
    if idx.exists():
        with idx.open(encoding='utf-8-sig',errors='replace') as fh:
            for line in fh:
                try:
                    r=json.loads(line)
                    if isinstance(r,dict) and r.get('id'):found[r['id']]=r
                except ValueError:continue
    # Old/missing index still supports articles and videos separately.
    for sub,kind in [('articles','web'),('videos','video')]:
        for f in sorted((ROOT/'output'/sub).glob('*.json')):
            data=read_json(f)
            if not isinstance(data,dict):continue
            rid=data.get('id') or f.stem
            if rid not in found:found[rid]={'id':rid,'type':kind}
            for key in ('title','source_url','source_name','content','images','timestamps','processing_status','crawl_status'):
                if (not found[rid].get(key)) and data.get(key):found[rid][key]=data[key]
    # Merge source registry for IDs with no media.
    urlpath=ROOT/'urls.csv'
    if urlpath.exists():
        with urlpath.open(encoding='utf-8-sig',newline='') as fh:
            for r in csv.DictReader(fh):
                rid=r.get('id')
                if not rid:continue
                obj=found.setdefault(rid,{'id':rid})
                obj.setdefault('type',r.get('type','web'))
                obj.setdefault('source_url',r.get('url',''))
                obj.setdefault('title',r.get('title_hint') or r.get('title') or rid)
                obj.setdefault('source_name',r.get('publisher',''))
                obj.setdefault('topic_hint',r.get('topic',''))
    with connect() as db:
        for rid,r in found.items():
            if rid.startswith('manual_'):continue
            images=r.get('images') if isinstance(r.get('images'),list) else []
            segments=r.get('timestamps') if isinstance(r.get('timestamps'),list) else []
            db.execute('''INSERT INTO sources(id,type,title,url,source_name,topic,raw_status,content,image_json,video_json,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET type=excluded.type,title=excluded.title,url=excluded.url,source_name=excluded.source_name,topic=excluded.topic,raw_status=excluded.raw_status,content=excluded.content,image_json=excluded.image_json,video_json=excluded.video_json,updated_at=excluded.updated_at''',(
                rid,r.get('type','web'),r.get('title') or rid,r.get('source_url') or r.get('url') or '',r.get('source_name') or r.get('publisher') or '',r.get('topic_hint') or '',r.get('processing_status') or r.get('crawl_status') or 'pending',safe_excerpt(r.get('content',''),320),json.dumps(images[:24],ensure_ascii=False),json.dumps(segments[:100],ensure_ascii=False),stamp()))
    return len(found)

def verification():
    p=ROOT/'report/source_verification.csv'
    grouped={}
    if p.exists():
        with p.open(encoding='utf-8-sig',newline='') as fh:
            for r in csv.DictReader(fh):
                k=r.get('claim_id','').strip()
                if not k:continue
                x=grouped.setdefault(k,{'id':k,'claim':'','verdict':'','conclusion':'','evidence':[],'crawled':[]})
                for field in ('claim','verdict','conclusion'):
                    if r.get(field):x[field]=r[field]
                role='evidence' if r.get('role')=='evidence' else 'crawled'
                x[role].append({'source':r.get('source_name',''),'url':r.get('source_url',''),'finding':r.get('finding',''),'quote':r.get('quote',''),'location':r.get('location','')})
    return grouped

def features():
    with connect() as db:return [dict(r) for r in db.execute('SELECT * FROM features ORDER BY rowid')]

def source_list(q='',kind='',limit=200):
    sql='SELECT id,type,title,url,source_name,raw_status,content,image_json,video_json FROM sources WHERE 1=1';args=[]
    if kind in ('web','video'):sql+=' AND type=?';args.append(kind)
    if q:sql+=' AND (title LIKE ? OR content LIKE ? OR source_name LIKE ?)';args.extend(['%'+q+'%']*3)
    sql+=' ORDER BY CASE WHEN content="" THEN 1 ELSE 0 END, id LIMIT ?';args.append(limit)
    with connect() as db:return [dict(r) for r in db.execute(sql,args)]

def counts():
    with connect() as db:
        return {'sources':db.execute('SELECT count(*) FROM sources').fetchone()[0], 'articles':db.execute('SELECT count(*) FROM sources WHERE type="web" AND content!=""').fetchone()[0], 'videos':db.execute('SELECT count(*) FROM sources WHERE type="video"').fetchone()[0]}
