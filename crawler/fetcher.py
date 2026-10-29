import time
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser
import requests
from bs4 import BeautifulSoup

HEADERS={'User-Agent':'GuanyinKnowledgeCrawler/1.0 (university coursework; respects robots.txt)'}
RETRY_CODES={429,500,502,503,504}
ROBOTS_CACHE={}

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

def fetch_web(url,timeout=15,retries=2,respect_robots=True):
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
                return blank(r.url,kind,f'HTTP {r.status_code}',r.status_code,attempt,time.monotonic()-started)
            kind=r.headers.get('Content-Type','').lower()
            if 'html' not in kind and 'xml' not in kind:
                return blank(r.url,'unavailable',f'不支援的 Content-Type: {kind}',r.status_code,attempt,time.monotonic()-started)
            if not r.encoding or r.encoding.lower()=='iso-8859-1':r.encoding=r.apparent_encoding or 'utf-8'
            soup=BeautifulSoup(r.text,'html.parser')
            title=soup.title.get_text(' ',strip=True) if soup.title else ''
            links=[];seen=set()
            for a in soup.select('a[href]'):
                link=urljoin(r.url,a.get('href',''))
                parsed=urlparse(link)
                if parsed.scheme not in ('http','https'):continue
                link=parsed._replace(fragment='').geturl()
                if link not in seen:seen.add(link);links.append(link)
            return dict(status='success',reason='',http_status=r.status_code,final_url=r.url,title=title,source_name=urlparse(r.url).netloc,html=r.text,links=links,attempts=attempt,elapsed_ms=round((time.monotonic()-started)*1000))
        except requests.exceptions.RequestException as e:
            if attempt<=retries:time.sleep(min(2**(attempt-1),8));continue
            return blank(url,'failed',f'{type(e).__name__}: {e}',attempts=attempt,elapsed=time.monotonic()-started)
