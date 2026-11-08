import time
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser
import requests
from bs4 import BeautifulSoup

HEADERS={'User-Agent':'GuanyinKnowledgeCrawler/1.0 (university coursework; respects robots.txt)'}
IMAGE_HEADERS={'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36','Accept':'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8','Sec-Fetch-Dest':'image','Sec-Fetch-Mode':'no-cors','Sec-Fetch-Site':'cross-site'}
RETRY_CODES={429,500,502,503,504}
ROBOTS_CACHE={}

def _needs_browser_render(html,title=''):
    """Detect an empty JS shell or browser challenge without rejecting normal pages."""
    low_title=(title or '').lower()
    if any(x in low_title for x in ('just a moment','cloudflare','access denied','attention required')):
        return True
    soup=BeautifulSoup(html or '','html.parser')
    text=' '.join(soup.get_text(' ',strip=True).split())
    if len(text)<=250 and soup.select_one('#app-root,#root,[data-reactroot]'):
        return True
    if len(text)<=250 and soup.select_one('noscript') and ('javascript' in soup.get_text(' ',strip=True).lower()):
        return True
    return False

def _rendered_result(url,timeout):
    from .browser_renderer import render_page
    rendered=render_page(url,timeout=timeout)
    soup=BeautifulSoup(rendered['html'],'html.parser')
    title=soup.title.get_text(' ',strip=True) if soup.title else rendered.get('title','')
    sample=' '.join(soup.get_text(' ',strip=True).split())[:2500].lower()
    challenge_text=(title+' '+sample).lower()
    if any(marker in challenge_text for marker in ('just a moment','cloudflare','anti-ddos flood protection',
                                                    'access denied','attention required')):
        raise RuntimeError(f'瀏覽器仍停留在驗證／反爬頁: {title[:120]}')
    return dict(status='success',reason='browser_rendered',http_status=200,
                final_url=rendered['final_url'],title=title,
                source_name=urlparse(rendered['final_url']).netloc,
                html=rendered['html'],links=rendered['links'],
                image_headers=rendered.get('image_headers',{}),attempts=1,
                elapsed_ms=rendered['elapsed_ms'])

def allowed_by_robots(url,timeout=8):
    origin=f'{urlparse(url).scheme}://{urlparse(url).netloc}'
    if origin not in ROBOTS_CACHE:
        robots_url=origin+'/robots.txt'
        try:
            r=requests.get(robots_url,headers=HEADERS,timeout=timeout)
            if r.status_code in (401,403):ROBOTS_CACHE[origin]=False
            elif r.status_code>=500:ROBOTS_CACHE[origin]=None
            elif r.status_code==404:ROBOTS_CACHE[origin]=True
            elif r.ok:
                rp=RobotFileParser();rp.parse(r.text.splitlines());ROBOTS_CACHE[origin]=rp
            else:ROBOTS_CACHE[origin]=None
        except requests.RequestException:ROBOTS_CACHE[origin]=None
    rp=ROBOTS_CACHE[origin]
    if rp is None:return None
    if isinstance(rp,bool):return rp
    return rp.can_fetch(HEADERS['User-Agent'],url)

def blank(url,status,reason,code=None,attempts=0,elapsed=0):
    return dict(status=status,reason=reason,http_status=code,final_url=url,title='',source_name=urlparse(url).netloc,html='',links=[],attempts=attempts,elapsed_ms=round(elapsed*1000))

def fetch_web(url,timeout=15,retries=2,respect_robots=True,browser_fallback=True):
    started=time.monotonic()
    if respect_robots:
        allowed=allowed_by_robots(url)
        if allowed is False:return blank(url,'unavailable','robots.txt 不允許存取',elapsed=time.monotonic()-started)
        if allowed is None:return blank(url,'unavailable','無法確認 robots.txt，保守停止',elapsed=time.monotonic()-started)
    for attempt in range(1,retries+2):
        try:
            r=requests.get(url,headers=HEADERS,timeout=timeout,allow_redirects=True)
            if r.status_code in RETRY_CODES and attempt<=retries+1:
                if attempt<=retries:
                    delay=min(2**(attempt-1),8)
                    if r.headers.get('Retry-After','').isdigit():delay=min(max(delay,int(r.headers['Retry-After'])),30)
                    time.sleep(delay);continue
            if r.status_code>=400:
                kind='unavailable' if r.status_code in (401,403,429) else 'failed'
                if browser_fallback and r.status_code in (401,403,408,428,429,451,500,502,503,504):
                    try:
                        return _rendered_result(r.url,timeout)
                    except Exception as browser_error:
                        reason=f'HTTP {r.status_code}; browser fallback failed: {type(browser_error).__name__}: {browser_error}'
                        return blank(r.url,kind,reason,r.status_code,attempt,time.monotonic()-started)
                return blank(r.url,kind,f'HTTP {r.status_code}',r.status_code,attempt,time.monotonic()-started)
            kind=r.headers.get('Content-Type','').lower()
            if 'html' not in kind and 'xml' not in kind:
                return blank(r.url,'unavailable',f'不支援的 Content-Type: {kind}',r.status_code,attempt,time.monotonic()-started)
            if not r.encoding or r.encoding.lower()=='iso-8859-1':r.encoding=r.apparent_encoding or 'utf-8'
            soup=BeautifulSoup(r.text,'html.parser')
            title=soup.title.get_text(' ',strip=True) if soup.title else ''
            if browser_fallback and _needs_browser_render(r.text,title):
                try:
                    return _rendered_result(r.url,timeout)
                except Exception as browser_error:
                    # Preserve the HTTP success but make the rendering limitation explicit;
                    # article_parser will mark the empty body as needs_review.
                    render_reason=f'browser fallback failed: {type(browser_error).__name__}: {browser_error}'
                else:
                    render_reason=''
            else:
                render_reason=''
            links=[];seen=set()
            for a in soup.select('a[href]'):
                link=urljoin(r.url,a.get('href',''))
                parsed=urlparse(link)
                if parsed.scheme not in ('http','https'):continue
                link=parsed._replace(fragment='').geturl()
                if link not in seen:seen.add(link);links.append(link)
            image_headers=dict(IMAGE_HEADERS,Referer=r.url)
            return dict(status='success',reason=render_reason,http_status=r.status_code,final_url=r.url,title=title,source_name=urlparse(r.url).netloc,html=r.text,links=links,image_headers=image_headers,attempts=attempt,elapsed_ms=round((time.monotonic()-started)*1000))
        except requests.exceptions.RequestException as e:
            if attempt<=retries:time.sleep(min(2**(attempt-1),8));continue
            if browser_fallback:
                try:
                    return _rendered_result(url, timeout)
                except Exception as browser_error:
                    return blank(url,'failed',f'{type(e).__name__}: {e}; browser fallback failed: {type(browser_error).__name__}: {browser_error}',attempts=attempt,elapsed=time.monotonic()-started)
            return blank(url,'failed',f'{type(e).__name__}: {e}',attempts=attempt,elapsed=time.monotonic()-started)
