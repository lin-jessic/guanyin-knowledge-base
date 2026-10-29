"""依實際爬取紀錄產生可用來源清單；不修改老師的原始來源。"""
import argparse
import csv
import json
from collections import Counter
from pathlib import Path


def load_csv(path):
    with open(path, encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def write_csv(path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)


def main():
    p = argparse.ArgumentParser(description='從爬取報告挑出已確認成功的來源；不刪除原清單')
    p.add_argument('--urls', default='urls.csv')
    p.add_argument('--report', default='output/crawl_report.csv')
    p.add_argument('--out', default='output/filtered')
    p.add_argument('--min-html-bytes', type=int, default=1000)
    args = p.parse_args()
    urls_path, report_path, out = Path(args.urls), Path(args.report), Path(args.out)
    urls, report = load_csv(urls_path), load_csv(report_path)
    latest = {}
    for r in report:
        if r.get('id'):
            # 報告順序可能有舊紀錄；以 crawled_at 最新為準
            key = r['id']
            if key not in latest or (r.get('crawled_at') or '') >= (latest[key].get('crawled_at') or ''):
                latest[key] = r
    working, pending, excluded = [], [], []
    audit = []
    for src in urls:
        sid = src.get('id', '')
        record = latest.get(sid)
        role = src.get('source_role', 'content')
        typ = src.get('type', 'web')
        if not record:
            state, reason = 'untested', '未在 crawl_report.csv 找到該 ID 的紀錄'
            pending.append(src)
        elif typ == 'video':
            state, reason = 'video_handoff', '影片交由組員3；不按網頁 HTML 成功標準判定'
            pending.append(src)
        elif record.get('crawl_status') == 'success' and str(record.get('http_status')) == '200':
            html = Path('output/raw_html') / f'{sid}.html'
            if not html.is_file() or html.stat().st_size < args.min_html_bytes:
                state, reason = 'needs_content_check', 'HTTP 200，但 HTML 檔缺失或太小'
                pending.append(src)
            elif role == 'discovery':
                state, reason = 'working_directory', '目錄已可取得；僅作探索，不當正式文章'
                working.append(src)
            else:
                state, reason = 'working_http', 'HTTP 200 且有 HTML；仍需組員2確認正文'
                working.append(src)
        elif record.get('crawl_status') in ('pending_video', 'video_pending'):
            state, reason = 'video_handoff', '等待影片模組處理'
            pending.append(src)
        else:
            state = 'excluded_from_active'
            reason = f"{record.get('crawl_status','unknown')}：{record.get('reason','') or 'HTTP '+str(record.get('http_status',''))}"
            excluded.append(src)
        audit.append({**src, 'filter_status': state, 'filter_reason': reason,
                      'last_crawl_at': record.get('crawled_at','') if record else '',
                      'last_http_status': record.get('http_status','') if record else ''})

    fields = list(urls[0]) if urls else []
    write_csv(out/'urls_working.csv', working, fields)
    write_csv(out/'urls_pending.csv', pending, fields)
    write_csv(out/'urls_excluded.csv', excluded, fields)
    write_csv(out/'source_audit.csv', audit, list(audit[0]) if audit else fields)
    (out/'working_registry.json').write_text(json.dumps(working, ensure_ascii=False, indent=2),encoding='utf-8')
    print(f'總來源 {len(urls)}；可用 {len(working)}；待驗 {len(pending)}；排除 {len(excluded)}')
    print('備註：可用是 HTTP 與 HTML 初步通過，尚非正文人工審核通過。')
    print('結果資料夾：',out)
    print('狀態分布：', dict(Counter(x['filter_status'] for x in audit)))

if __name__ == '__main__':
    main()
