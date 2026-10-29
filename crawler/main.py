import argparse
import csv
import hashlib
import json
import time
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import urlsplit
from .url_manager import load_urls,canonical,is_video,valid_url
from .fetcher import fetch_web

FIELDS=['id','type','origin','topic','source_url','final_url','title','source_name','crawl_status','reason','http_status','attempts','elapsed_ms','link_count','sha256','changed','crawled_at','depth','parent_url']
KEYWORDS=('觀音','guanyin','kuangin','草漯','白沙岬','藻礁','大潭','崙坪','蓮花','hakka','沙丘')

def relevant_links(links,source_url,limit,allow_hosts):
    kept=[];seen=set()
    for link in links:
        host=(urlsplit(link).hostname or '').lower()
        if host not in allow_hosts:continue
        if not any(w in link.lower() for w in KEYWORDS):continue
        key=canonical(link)
        if key not in seen and key!=canonical(source_url):seen.add(key);kept.append(link)
        if len(kept)>=limit:break
    return kept

def read_previous(path):
    if not path.exists():return {}
    with path.open(encoding='utf-8-sig',newline='') as f:return {r['id']:r for r in csv.DictReader(f)}

def save_report(path,reports):
    path.parent.mkdir(exist_ok=True,parents=True)
    temp=path.with_suffix('.tmp')
    with temp.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,FIELDS,extrasaction='ignore');w.writeheader();w.writerows(reports.values())
    temp.replace(path)

def main():
    p=argparse.ArgumentParser(description='Guanyin crawler / member 1')
    p.add_argument('--urls',default='urls.csv');p.add_argument('--id');p.add_argument('--url')
    p.add_argument('--origin',choices=['teacher','extra']);p.add_argument('--explore',action='store_true')
    p.add_argument('--include-discovery',action='store_true')
    p.add_argument('--max-extra',type=int,default=2);p.add_argument('--delay',type=float,default=2)
    p.add_argument('--retry-failed',action='store_true');p.add_argument('--resume',action='store_true')
    p.add_argument('--timeout',type=int,default=15);p.add_argument('--retries',type=int,default=2)
    p.add_argument('--no-robots-check',action='store_true',help='僅在已有網站存取許可時使用')
    p.add_argument('--report',default='output/crawl_report.csv')
    a=p.parse_args()
    if a.delay<0 or a.max_extra<0 or a.retries<0:p.error('數值不能小於 0')
    entries=load_urls(a.urls)
    if not a.include_discovery and not a.id:
        entries=[r for r in entries if r.get('source_role')!='discovery']
    if a.origin:entries=[r for r in entries if r['origin']==a.origin]
    if a.id:entries=[r for r in entries if r['id']==a.id]
    if a.url:
        if not valid_url(a.url):p.error('指定的網址不合法')
        entries=[dict(id='manual_001',url=a.url,type='video' if is_video(a.url) else 'web',origin='manual',topic='')]
    if not entries:p.error('沒有可處理的網址')
    out=Path(a.report).parent
    (out/'raw_html').mkdir(parents=True,exist_ok=True)
    (out/'links').mkdir(parents=True,exist_ok=True)
    report_path=Path(a.report)
    reports=read_previous(report_path)
    pending=[]
    for entry in entries:
        old=reports.get(entry['id'],{})
        if a.resume and old.get('crawl_status') in ('success','pending_video'):continue
        if a.retry_failed and old.get('crawl_status') not in ('failed','unavailable'):continue
        pending.append(entry)
    visited=set();count=0
    allow_hosts={(urlsplit(e['url']).hostname or '').lower() for e in entries if e['type']=='web'}
    def process(e,depth=0,parent_url=''):
        nonlocal count
        url=e['url'];key=canonical(url)
        if key in visited:return
        visited.add(key);count+=1
        old=reports.get(e['id'],{})
        now=datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds')
        if e['type']=='video':
            result=dict(status='pending_video',reason='交由組員三處理，未宣稱已取得影片',http_status='',final_url=url,title='',source_name=urlsplit(url).hostname,html='',links=[],attempts=0,elapsed_ms=0)
        else:result=fetch_web(url,timeout=a.timeout,retries=a.retries,respect_robots=not a.no_robots_check)
        digest=hashlib.sha256(result['html'].encode('utf-8')).hexdigest() if result['status']=='success' else ''
        changed='unknown' if not old.get('sha256') or not digest else str(old['sha256']!=digest).lower()
        if result['status']=='success':
            (out/'raw_html'/f"{e['id']}.html").write_text(result['html'],encoding='utf-8')
            (out/'links'/f"{e['id']}.json").write_text(json.dumps(result['links'],ensure_ascii=False,indent=2),encoding='utf-8')
        reports[e['id']]=dict(id=e['id'],type=e['type'],origin=e.get('origin',''),topic=e.get('topic',''),source_url=url,final_url=result['final_url'],title=result['title'],source_name=result['source_name'],crawl_status=result['status'],reason=result['reason'],http_status=result['http_status'],attempts=result['attempts'],elapsed_ms=result['elapsed_ms'],link_count=len(result['links']),sha256=digest,changed=changed,crawled_at=now,depth=depth,parent_url=parent_url)
        save_report(report_path,reports)
        print(f"[{count}/{len(pending)}+延伸] {e['id']} {result['status']} (HTTP {result['http_status']}) {url[:80]}",flush=True)
        if a.delay>0 and e['type']=='web':time.sleep(a.delay)
        if a.explore and depth==0 and result['status']=='success':
            for i,link in enumerate(relevant_links(result['links'],result['final_url'],a.max_extra,allow_hosts),1):
                process(dict(id=f"{e['id']}_extra_{i:02d}",url=link,type='web',origin='discovered',topic=e.get('topic','')),1,url)
    for e in pending:process(e)
    print(f'本次處理 {count} 筆；已記錄 {len(reports)} 筆，報告：{report_path}')
if __name__=='__main__':main()
