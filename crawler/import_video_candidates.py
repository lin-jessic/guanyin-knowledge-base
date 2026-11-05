"""匯入已核對地理主題的額外 YouTube 影片；保留教師來源，對 video ID 去重。"""
import argparse
import csv
import re
from urllib.parse import parse_qs, urlparse
from .url_manager import read_rows, write_rows, FIELDS


def youtube_id(url):
    p = urlparse(url)
    host = (p.hostname or '').lower()
    host = host.removeprefix('www.').removeprefix('m.')
    if host == 'youtu.be':
        result = p.path.strip('/').split('/')[0]
    elif host == 'youtube.com':
        parts = p.path.strip('/').split('/')
        if parts and parts[0] == 'watch':
            result = parse_qs(p.query).get('v', [''])[0]
        elif len(parts) > 1 and parts[0] in ('shorts', 'embed', 'live'):
            result = parts[1]
        else:
            return None
    else:
        return None
    return result if re.fullmatch(r'[\w-]{11}', result) else None


def import_candidates(urls='urls.csv', candidates='data/extra_video_candidates.csv', dry_run=False):
    records = read_rows(urls)
    existing = {youtube_id(x['url']) for x in records if youtube_id(x['url'])}
    next_id = max((int(x['id'].split('_')[-1]) for x in records if re.fullmatch('extra_\\d+', x['id'])), default=0)
    with open(candidates, encoding='utf-8-sig', newline='') as f:
        new = list(csv.DictReader(f))
    added = []
    for c in new:
        vid = youtube_id(c['url'])
        if not vid or vid != c['video_id']:
            raise ValueError(f"URL 與影片 ID 不符：{c['url']}")
        if vid in existing:
            print(f'略過重複影片：{vid}')
            continue
        existing.add(vid)
        next_id += 1
        record = dict.fromkeys(FIELDS, '')
        record.update(id=f'extra_{next_id:03d}', url=c['url'], type='video', origin='extra',
                      title_hint=c['title'], topic=c['topic'], publisher=c['channel'], enabled='true',
                      geo_scope=c['scope'], source_role='content', review_status='video_candidate',
                      evidence='影片搜尋結果標題、頻道、介紹文字；仍需確認內容與使用權限',
                      notes=f"來源等級：{c['source_level']}；發布日期：{c['publication_date']}；{c['review_note']}")
        added.append(record)
    if not dry_run and added:
        write_rows(urls, records + added)
    print(f"新增候選：{len(added)} 筆（{'預覽，未寫入' if dry_run else '已寫入網址清單'}）")
    for r in added:
        print(f"{r['id']}: {r['title_hint']} | {r['url']}")
    print('提醒：加入來源名錄不代表字幕與影格已處理，請逐筆測試並遵守平台及著作權規範。')
    return added


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--urls', default='urls.csv')
    p.add_argument('--candidates', default='data/extra_video_candidates.csv')
    p.add_argument('--dry-run', action='store_true')
    a = p.parse_args()
    import_candidates(a.urls, a.candidates, a.dry_run)

if __name__ == '__main__':
    main()
