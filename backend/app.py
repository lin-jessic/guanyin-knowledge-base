"""Guanyin local-studies website. Run: py -3.12 -m backend.app"""
from __future__ import annotations
import json,os,secrets,sqlite3
from functools import wraps
from pathlib import Path
from urllib.parse import urlparse,parse_qs
from flask import Flask,render_template,request,redirect,url_for,session,abort,send_from_directory,flash
from . import store, gallery, gallery
from .content import TOPIC_MAP,TOPICS

ROOT=store.ROOT
app=Flask(__name__,template_folder=str(ROOT/'frontend/templates'),static_folder=str(ROOT/'frontend/static'))
app.secret_key=os.getenv('GUANYIN_SECRET_KEY') or secrets.token_hex(32)
app.config.update(SESSION_COOKIE_HTTPONLY=True,SESSION_COOKIE_SAMESITE='Lax',MAX_CONTENT_LENGTH=1024*1024)

@app.after_request
def security_headers(resp):
    resp.headers['X-Content-Type-Options']='nosniff'
    resp.headers['X-Frame-Options']='SAMEORIGIN'
    resp.headers['Referrer-Policy']='strict-origin-when-cross-origin'
    resp.headers['Cache-Control']='no-store' if request.path.startswith('/settings') else 'no-cache'
    return resp

def admin_only(fn):
    @wraps(fn)
    def wrap(*args,**kwargs):
        if not session.get('admin'):return redirect(url_for('login',next=request.path))
        return fn(*args,**kwargs)
    return wrap

def csrf():
    if 'csrf' not in session:session['csrf']=secrets.token_urlsafe(32)
    return session['csrf']

def check_csrf():
    if not secrets.compare_digest(request.form.get('csrf',''),session.get('csrf','')):abort(400,'表單驗證失敗')

@app.context_processor
def inject():return {'topics':TOPICS,'csrf_token':csrf}

@app.route('/')
def home():
    data=store.features()
    return render_template('home.html',features=[x for x in data if x['publication']=='published'],counts=store.counts(),topicmap=TOPIC_MAP,gallery_preview=gallery.gallery_listing(per_page=8)[0])

@app.route('/topics')
def topics_page():return render_template('topics.html',topicmap=TOPIC_MAP)

@app.route('/topics/<slug>')
def topic_detail(slug):
    topic=TOPIC_MAP.get(slug)
    if not topic:abort(404)
    return render_template('topic.html',topic=topic,features=[x for x in store.features() if x['topic']==slug],topicmap=TOPIC_MAP)

@app.route('/research')
def research_index():return render_template('research_index.html',features=store.features(),topicmap=TOPIC_MAP)

@app.route('/research/<slug>')
def research(slug):
    f=next((r for r in store.features() if r['slug']==slug),None)
    if not f:abort(404)
    claims=store.verification()
    selected=[claims[k] for k in json.loads(f['claims']) if k in claims]
    terms=json.loads(f['tags'])
    matches=[];seen=set()
    for term in terms:
        for s in store.source_list(term,limit=8):
            if s['id'] not in seen:matches.append(s);seen.add(s['id'])
    return render_template('research.html',f=f,topic=TOPIC_MAP[f['topic']],questions=json.loads(f['questions']),tags=terms,claims=selected,sources=matches[:14])

@app.route('/library')
def library():
    q=request.args.get('q','').strip()[:80];kind=request.args.get('type','')
    recs=store.source_list(q,kind,limit=120)
    for rec in recs:rec['photos']=store.public_photos(rec,1)
    return render_template('library.html',q=q,kind=kind,records=recs)

@app.route('/source/<rid>')
def source_detail(rid):
    with store.connect() as db:
        row=db.execute('SELECT * FROM sources WHERE id=?',(rid,)).fetchone()
    if not row:abort(404)
    rec=dict(row)
    approved=[]
    admin_previews=[]
    try: raw_images=json.loads(rec.get('image_json') or '[]')
    except ValueError:raw_images=[]
    with store.connect() as db:
        for it in raw_images[:24]:
            if not isinstance(it,dict):continue
            path=str(it.get('file') or '').replace('\\','/')
            if not path.startswith('images/') or '..' in Path(path).parts:continue
            if session.get('admin') and (ROOT/'output'/path).is_file():
                admin_previews.append({'path':path,'caption':str(it.get('caption') or rec['title'])[:150]})
            ok=db.execute('SELECT allow_public FROM media_rights WHERE path=?',(path,)).fetchone()
            if ok and ok[0]==1 and (ROOT/'output'/path).is_file():
                approved.append({'path':path,'caption':str(it.get('caption') or rec['title'])[:150]})
    # External source excerpts, not full reproduction; associated images preview only in admin.
    return render_template('source.html',rec=rec,segments=json.loads(rec['video_json'] or '[]'),approved=approved,admin_previews=admin_previews,article_photos=gallery.photos_for_record(rec))

@app.route('/videos')
def videos_public():
    items=store.source_list(kind='video',limit=50)
    for item in items:
        u=urlparse(item.get('url') or '')
        vid=''
        if u.hostname in ('www.youtube.com','youtube.com','m.youtube.com'):
            vid=parse_qs(u.query).get('v',[''])[0]
            if not vid and u.path.startswith('/shorts/'):vid=u.path.split('/')[2]
        elif u.hostname in ('youtu.be','www.youtu.be'):
            vid=u.path.strip('/').split('/')[0]
        item['youtube_id']=vid if len(vid)==11 and all(x.isalnum() or x in '-_' for x in vid) else ''
        item['photos']=store.public_photos(item)
    return render_template('videos_public.html',records=items)

@app.route('/timeline')
def timeline():
    rows=[('1898','燈塔興建記載','來源紀錄提及白沙岬燈塔於 1898 年動工；完工年份另有不同版本。','C04'),('1900 / 1901','燈塔完工年份的兩種說法','文化部公告與其他政府來源對竣工時間記載不一致，仍待原始史料複核。','C04'),('2014','行政區沿革','來源查證紀錄指出觀音鄉隨桃園升格改制為區；影音曾出現不同年份。','C02'),('2021','文化資產指定','小組查證紀錄引用文化部公告，指出白沙岬燈塔於 2021 年指定為國定古蹟。','C03')]
    return render_template('timeline.html',events=rows)

@app.route('/evidence')
def evidence():return render_template('evidence.html',claims=store.verification())

@app.route('/map')
def map_page():
    with store.connect() as db:
        pts=[dict(x) for x in db.execute('SELECT * FROM places WHERE reviewed=1 AND latitude BETWEEN -90 AND 90 AND longitude BETWEEN -180 AND 180')]
    for item in pts:
        item['sources']=store.related_sources(item,12)
        item['photos']=next((s['photos'] for s in item['sources'] if s['photos']),[])
    return render_template('map.html',places=pts,topicmap=TOPIC_MAP)

@app.route('/about')
def about():return render_template('about.html')

@app.route('/media/<path:rel>')
def media(rel):
    # Never expose arbitrary files; only reviewed public image paths.
    p=Path(rel)
    if p.is_absolute() or '..' in p.parts or p.suffix.lower() not in ('.jpg','.jpeg','.png','.webp','.gif'):abort(404)
    with store.connect() as db:
        allowed=db.execute('SELECT allow_public FROM media_rights WHERE path=?',(rel,)).fetchone()
    if not allowed or allowed['allow_public']!=1:abort(404)
    return send_from_directory(ROOT/'output',rel)


# Photo archive: actual crawler files, unverified rights explicitly labelled.
@app.route("/gallery")
def gallery_page():
    try: page=max(1,int(request.args.get('page','1')))
    except ValueError:page=1
    q=request.args.get('q','').strip()[:60]
    photos,total,page,stats=gallery.gallery_listing(q,page)
    return render_template('gallery.html',photos=photos,total=total,page=page,q=q,stats=stats)

@app.route("/gallery-image/<path:rel>")
def gallery_image(rel):
    # Serve only files referenced by existing article JSON; no arbitrary disk paths.
    path=gallery.normalize_path(rel)
    if path is None:abort(404)
    # Unreviewed images are for local teaching/review only; opt-in for LAN usage.
    if request.remote_addr not in ('127.0.0.1','::1') and os.getenv('GUANYIN_LAN_PHOTO_PREVIEW')!='1':
        with store.connect() as db:
            right=db.execute('SELECT allow_public FROM media_rights WHERE path=?',(path,)).fetchone()
        if not right or right[0] != 1:abort(403)
    return send_from_directory(ROOT/'output',path)

@app.route('/settings/login',methods=['GET','POST'])
def login():
    configured=os.getenv('GUANYIN_ADMIN_PASSWORD','')
    if request.method=='POST':
        check_csrf()
        if not configured:
            flash('請先設定 GUANYIN_ADMIN_PASSWORD 環境變數。','error')
        elif secrets.compare_digest(request.form.get('password',''),configured):
            session.clear();session['admin']=True;csrf()
            return redirect(url_for('settings'))
        else:flash('密碼不正確。','error')
    return render_template('login.html',configured=bool(configured))

@app.route('/settings/logout',methods=['POST'])
@admin_only
def logout():
    check_csrf();session.clear();return redirect(url_for('home'))

@app.route('/settings')
@admin_only
def settings():
    return render_template('settings.html',counts=store.counts(),features=store.features(),logs=read_logs(),legacy=['index.html','articles.html','videos.html','video_quality.html','video_recovery.html','knowledge.html'])

def read_logs():
    with store.connect() as db:return [dict(r) for r in db.execute('SELECT * FROM review_log ORDER BY id DESC LIMIT 30')]

@app.route('/settings/reimport',methods=['POST'])
@admin_only
def reimport():
    check_csrf();n=store.import_outputs();flash(f'已重新讀取本機輸出，共 {n} 筆候選紀錄；原始檔與人工審核狀態未改動。','ok')
    return redirect(url_for('settings'))

@app.route('/settings/feature/<slug>',methods=['POST'])
@admin_only
def update_feature(slug):
    check_csrf()
    action=request.form.get('action','draft')
    if action not in ('draft','published'):abort(400)
    body=request.form.get('editor_body','').strip()[:12000]
    note=request.form.get('note','').strip()[:400]
    # Publishing requires non-empty manually edited text, to avoid auto-publishing raw crawl text.
    if action=='published' and len(body)<120:
        flash('公開發布前，請先完成至少 120 字人工編輯專題內容。','error')
        return redirect(url_for('settings')+'#editor-'+slug)
    with store.connect() as db:
        old=db.execute('SELECT slug FROM features WHERE slug=?',(slug,)).fetchone()
        if not old:abort(404)
        db.execute('UPDATE features SET publication=?,editor_body=?,updated_at=? WHERE slug=?',(action,body,store.stamp(),slug))
        db.execute('INSERT INTO review_log(slug,action,note,created_at) VALUES(?,?,?,?)',(slug,action,note,store.stamp()))
    flash('人工編輯與發布狀態已儲存。','ok')
    return redirect(url_for('settings')+'#editor-'+slug)

@app.route('/settings/media',methods=['POST'])
@admin_only
def update_media():
    check_csrf()
    path=request.form.get('path','').strip()
    p=Path(path)
    if p.is_absolute() or '..' in p.parts or not path.startswith('images/') or p.suffix.lower() not in ('.jpg','.jpeg','.png','.webp','.gif') or not (ROOT/'output'/p).is_file():
        flash('圖片路徑不合法或檔案不存在。','error');return redirect(url_for('settings'))
    allow=1 if request.form.get('allow')=='1' else 0
    with store.connect() as db:
        db.execute('INSERT INTO media_rights(path,allow_public) VALUES(?,?) ON CONFLICT(path) DO UPDATE SET allow_public=excluded.allow_public',(path,allow))
    flash('圖片發布設定已更新。公開前仍需自行確認授權。','ok')
    return redirect(url_for('settings'))

@app.route('/settings/place',methods=['POST'])
@admin_only
def update_place():
    check_csrf()
    try:
        lat=float(request.form.get('lat',''));lng=float(request.form.get('lng',''))
        if not (-90<=lat<=90 and -180<=lng<=180):raise ValueError
    except ValueError:
        flash('請輸入合法經緯度。','error');return redirect(url_for('settings'))
    name=request.form.get('name','').strip()[:120];url=request.form.get('source_url','').strip()[:500]
    if not name or urlparse(url).scheme not in ('https','http') or not urlparse(url).netloc:
        flash('地點名稱與來源網址不可為空。','error');return redirect(url_for('settings'))
    topic=request.form.get('topic','')
    if topic not in TOPIC_MAP:topic='land'
    terms=request.form.get('source_ids','').strip()[:300]
    description=request.form.get('description','').strip()[:650]
    with store.connect() as db:
        db.execute('INSERT INTO places(name,topic,latitude,longitude,source_url,reviewed,source_ids,description,coord_note) VALUES(?,?,?,?,?,1,?,?,?)',(name,topic,lat,lng,url,terms,description,'由管理員確認的點位'))
    flash('已加入具有來源的地圖點位。','ok');return redirect(url_for('settings'))

@app.route('/settings/legacy/<name>')
@admin_only
def legacy(name):
    if name not in ('index.html','articles.html','videos.html','video_quality.html','video_recovery.html','knowledge.html'):abort(404)
    # The old pages may reference relative site/assets files; serve them from same /settings/legacy prefix.
    return send_from_directory(ROOT/'site',name)

@app.route('/settings/legacy/assets/<path:rel>')
@admin_only
def legacy_assets(rel):
    if '..' in Path(rel).parts:abort(404)
    return send_from_directory(ROOT/'site/assets',rel)

@app.route('/settings/output/<path:rel>')
@admin_only
def legacy_output(rel):
    if '..' in Path(rel).parts:abort(404)
    if Path(rel).suffix.lower() not in ('.jpg','.jpeg','.png','.webp','.gif'):abort(404)
    return send_from_directory(ROOT/'output',rel)

@app.route('/settings/raw-image/<path:rel>')
@admin_only
def admin_image(rel):
    if '..' in Path(rel).parts or not rel.startswith('images/') or Path(rel).suffix.lower() not in ('.jpg','.jpeg','.png','.webp','.gif'):abort(404)
    return send_from_directory(ROOT/'output',rel)

@app.route('/settings/images')
@admin_only
def images():
    paths=sorted((ROOT/'output/images').glob('*.jpg'))[:180]
    return render_template('images.html',images=[str(p.relative_to(ROOT/'output')).replace('\\','/') for p in paths])

@app.cli.command('sync-data')
def sync_data():print(f'Imported {store.import_outputs()} source entries.')

store.init()
if __name__=='__main__':
    # Local only; do not expose admin service via a public tunnel.
    store.import_outputs()
    app.run(host='127.0.0.1',port=5000,debug=False)
