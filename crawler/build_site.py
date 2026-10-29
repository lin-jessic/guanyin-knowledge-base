import argparse,csv,json
from pathlib import Path
from .url_manager import read_rows

def build(out='site/index.html',urls='urls.csv',report='output/crawl_report.csv'):
    rows=read_rows(urls);status={}
    if Path(report).exists():
        with open(report,encoding='utf-8-sig',newline='') as f:status={r['id']:r for r in csv.DictReader(f)}
    for row in rows:
        info=status.get(row['id'],{})
        row['crawl_status']=info.get('crawl_status','not_tested')
        row['http_status']=info.get('http_status','')
        row['reason']=info.get('reason','')
    data=json.dumps(rows,ensure_ascii=False).replace('<','\\u003c').replace('>','\\u003e')
    template=Path(__file__).with_name('site_template.html').read_text(encoding='utf-8')
    path=Path(out);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(template.replace('/*SOURCE_DATA*/null',data),encoding='utf-8')
    print(f'網站建立完成：{path}，共 {len(rows)} 筆來源')
    return path

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',default='site/index.html');a=p.parse_args();build(out=a.output)
if __name__=='__main__':main()
