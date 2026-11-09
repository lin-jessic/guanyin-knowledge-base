"""Apply additive photo wall patch to CURRENT repository, retaining teammate files.
Run from repository root: py -3.12 install_gallery.py
"""
from pathlib import Path
import shutil
import re
ROOT = Path.cwd()
PATCH = Path(__file__).resolve().parent
assert (ROOT/'backend/app.py').is_file() and (ROOT/'frontend/templates/base.html').is_file(), '請在 guanyin-knowledge-base 專案根目錄執行'

for path in ['backend/gallery.py', 'frontend/templates/gallery.html', 'frontend/static/css/gallery.css']:
    dest=ROOT/path
    dest.parent.mkdir(parents=True,exist_ok=True)
    
    if (PATCH/path).resolve() != dest.resolve():
        shutil.copy2(PATCH/path,dest)


def update(path, do):
    f=ROOT/path
    old=f.read_text(encoding='utf-8')
    new=do(old)
    if new != old:
        backup=f.with_name(f.name+'.before_gallery.bak')
        if not backup.exists():backup.write_text(old,encoding='utf-8')
        f.write_text(new,encoding='utf-8')
        print('更新',path)
    else:print('不需修改',path)


def app_patch(s):
    if 'from . import gallery' not in s:
        s=s.replace('from . import store','from . import store, gallery',1)
    if '@app.route("/gallery")' not in s:
        extra='''\n# Photo archive: actual crawler files, unverified rights explicitly labelled.\n@app.route("/gallery")\ndef gallery_page():\n    try: page=max(1,int(request.args.get('page','1')))\n    except ValueError:page=1\n    q=request.args.get('q','').strip()[:60]\n    photos,total,page,stats=gallery.gallery_listing(q,page)\n    return render_template('gallery.html',photos=photos,total=total,page=page,q=q,stats=stats)\n\n@app.route("/gallery-image/<path:rel>")\ndef gallery_image(rel):\n    # Serve only files referenced by existing article JSON; no arbitrary disk paths.\n    path=gallery.normalize_path(rel)\n    if path is None:abort(404)\n    # Unreviewed images are for local teaching/review only; opt-in for LAN usage.\n    if request.remote_addr not in ('127.0.0.1','::1') and os.getenv('GUANYIN_LAN_PHOTO_PREVIEW')!='1':\n        with store.connect() as db:\n            right=db.execute('SELECT allow_public FROM media_rights WHERE path=?',(path,)).fetchone()\n        if not right or right[0] != 1:abort(403)\n    return send_from_directory(ROOT/'output',path)\n\n'''
        key="@app.route('/settings/login'"
        assert key in s, 'app.py 缺少預期的登入路由，請人工檢查'
        s=s.replace(key,extra+key,1)
    if 'gallery_preview=' not in s:
        needle="counts=store.counts(),topicmap=TOPIC_MAP)"
        assert needle in s, '首頁返回模板結構已改，請人工檢查'
        s=s.replace(needle,"counts=store.counts(),topicmap=TOPIC_MAP,gallery_preview=gallery.gallery_listing(per_page=8)[0])",1)
    if 'article_photos=' not in s:
        key="admin_previews=admin_previews)"
        if key in s:
            s=s.replace(key,"admin_previews=admin_previews,article_photos=gallery.photos_for_record(rec))",1)
        else:
            pattern=r"(return render_template\('source\.html',[^\n]*)(\))"
            s,n=re.subn(pattern,r"\1,article_photos=gallery.photos_for_record(rec)\2",s,count=1)
            assert n==1, '來源詳情模板結構已改' 
    return s


def base_patch(s):
    if "url_for('gallery_page')" not in s:
        anchor='<a href="{{url_for(\'library\')}}">資料索引</a>'
        assert anchor in s,'base.html 找不到來源索引連結'
        s=s.replace(anchor,anchor+'<a href="{{url_for(\'gallery_page\')}}">觀音影像誌</a>',1)
    return s


def home_patch(s):
    if 'HOME PHOTO WALL' not in s:
        block='''\n<!-- HOME PHOTO WALL -->\n<section class="section container"><div class="section-heading"><div><p class="kicker">LOCAL PHOTO ARCHIVE</p><h2>看見觀音・地方影像</h2><p>從採集的文章影像中閱讀地景與文化，點選照片可回溯來源。尚未完成的授權資訊會清楚標示。</p></div><a href="{{url_for('gallery_page')}}" class="all-link">瀏覽完整照片牆 →</a></div><div class="home-photo-wall">{% for photo in gallery_preview %}<a href="{{url_for('source_detail',rid=photo.id)}}"><img loading="lazy" src="{{url_for('gallery_image',rel=photo.path)}}" alt="{{photo.caption}}"><span>{{photo.caption}}</span></a>{% else %}<p>尚無可展示的影像檔。</p>{% endfor %}</div><p class="subtle">這些影像為來源擷取成果，非全數已完成授權審查；分享前請核對各來源使用條件。</p></section>\n'''
        s=s.replace('{% endblock %}',block+'{% endblock %}',1)
    return s


def source_patch(s):
    if 'ARTICLE PHOTO WALL' not in s:
        block='''\n<!-- ARTICLE PHOTO WALL -->\n{% if article_photos %}<section><h2>這篇文章的影像紀錄</h2><p class="subtle">圖片來源於此文章的實際爬取成果。圖說依擷取資料整理，標示授權待核對者請勿擅自轉載。</p><div class="article-photo-grid">{% for photo in article_photos %}<figure><img loading="lazy" src="{{url_for('gallery_image',rel=photo.path)}}" alt="{{photo.caption}}"><figcaption>{{photo.caption}}<div class="photo-warning">{{photo.rights}}{% if photo.image_source.startswith('http') %} · <a href="{{photo.image_source}}" target="_blank" rel="noopener noreferrer">原圖出處</a>{% endif %}</div></figcaption></figure>{% endfor %}</div></section>{% endif %}\n'''
        s=s.replace('{% endblock %}',block+'{% endblock %}',1)
    if "css/gallery.css" not in s:
        s=s.replace("{% block body %}","{% block head %}<link rel=\"stylesheet\" href=\"{{url_for('static',filename='css/gallery.css')}}\">{% endblock %}{% block body %}",1)
    return s


def store_patch(s):
    # Improve only the excerpt formatter. Leave all crawling/import/storage logic untouched.
    start=s.find('def safe_excerpt(')
    end=s.find('\ndef import_outputs(',start)
    assert start>=0 and end>start,'找不到 safe_excerpt'
    revised='''def safe_excerpt(s, n=260):
    """Remove Markdown images, navigation, HTML/JS noise before truncation."""
    import html as _html
    s = _html.unescape(str(s or ''))
    s = re.sub(r'!\\[[^\\]]*\\]\\([^\\n)]*(?:\\([^)]*\\)[^\\n)]*)?\\)', ' ', s)
    s = re.sub(r'\\[([^\\]]+)\\]\\([^\\n)]*\\)', r'\\1', s)
    s = re.sub(r'<(?:script|style|nav|header|footer)\\b[^>]*>.*?</(?:script|style|nav|header|footer)>', ' ', s, flags=re.I|re.S)
    s = re.sub(r'<[^>]+>', ' ', s)
    s = re.sub(r'(?m)^.*(?:\\$\\(|document\\.|querySelector|addEventListener|function\\s*\\(|javascript:|window\\.|console\\.|const\\s+\\w+\\s*=|let\\s+\\w+\\s*=|\\bvar\\s+\\w+\\s*=).*$', ' ', s)
    s = re.sub(r'(?m)^\\s{0,3}#{1,6}\\s*', '', s)
    s = re.sub(r'(?m)^\\s*[-*]\\s+', ' ', s)
    s = re.sub(r'(?m)^\\s*\\|(?:[- :]+\\|)+\\s*$', ' ', s)
    s = re.sub(r'(?m)^\\s*---+\\s*$', ' ', s)
    s = re.sub(r'[`*_{}]+', ' ', s)
    s = re.sub(r'\\s+', ' ', s).strip(' -|;，、')
    return s[:n].rstrip() + ('…' if len(s)>n else '')

'''
    return s[:start]+revised+s[end+1:]

update('backend/app.py',app_patch)
update('backend/store.py',store_patch)
update('frontend/templates/base.html',base_patch)
update('frontend/templates/home.html',home_patch)
update('frontend/templates/source.html',source_patch)
# Appended CSS in a dedicated file; add to base once for home wall.
def inject_css(s):
    marker="<link rel=\"stylesheet\" href=\"{{ url_for('static',filename='css/site.css') }}\">"
    addition="<link rel=\"stylesheet\" href=\"{{ url_for('static',filename='css/gallery.css') }}\">"
    return s.replace(marker,marker+addition,1) if addition not in s else s
update('frontend/templates/base.html',inject_css)
with (ROOT/'frontend/static/css/gallery.css').open('a',encoding='utf-8') as f:
    f.write('\n.home-photo-wall{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}.home-photo-wall a{position:relative;display:block;overflow:hidden;background:#e1e5dd;height:190px}.home-photo-wall img{width:100%;height:100%;object-fit:cover}.home-photo-wall span{position:absolute;inset:auto 0 0;background:linear-gradient(transparent,#172b25ca);color:white;padding:24px 10px 9px;font-size:12px}@media(max-width:680px){.home-photo-wall{grid-template-columns:repeat(2,minmax(0,1fr))}}\n')
print('完成。保留既有 output、crawler、storage；修改前的檔案備份為 .before_gallery.bak')
