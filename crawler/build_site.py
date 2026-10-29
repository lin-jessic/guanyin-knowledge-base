"""用來源表、爬取報告及篩選審核結果建立本機靜態展示頁。"""
import argparse
import csv
import json
from pathlib import Path
from .url_manager import read_rows


def load_csv(path):
    if not Path(path).exists():
        return []
    with open(path, encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def build(out='site/index.html', urls='urls.csv', report='output/crawl_report.csv', audit='output/filtered/source_audit.csv'):
    rows = read_rows(urls)
    records = {}
    for r in load_csv(report):
        key = r.get('id')
        if key and (key not in records or r.get('crawled_at','') >= records[key].get('crawled_at','')):
            records[key] = r
    audits = {r['id']: r for r in load_csv(audit) if r.get('id')}
    for r in rows:
        log = records.get(r['id'], {})
        ar = audits.get(r['id'], {})
        for k in ('crawl_status','http_status','reason','crawled_at'):
            r[k] = log.get(k, '')
        r['filter_status'] = ar.get('filter_status', 'not_audited')
        r['filter_reason'] = ar.get('filter_reason', '請先執行來源篩選工具')
        r['last_http_status'] = ar.get('last_http_status', log.get('http_status',''))
    payload = json.dumps(rows, ensure_ascii=False).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
    template = Path(__file__).with_name('site_template.html').read_text(encoding='utf-8')
    path = Path(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(template.replace('/*SOURCE_DATA*/null', payload), encoding='utf-8')
    print(f'網站建立完成：{path}（{len(rows)} 筆來源）')
    return path


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--output',default='site/index.html')
    p.add_argument('--audit',default='output/filtered/source_audit.csv')
    p.add_argument('--report',default='output/crawl_report.csv')
    a=p.parse_args()
    build(out=a.output,audit=a.audit,report=a.report)

if __name__=='__main__':
    main()
