"""組員 4 測試：python -m unittest tests.test_knowledge -v

用暫存資料夾模擬「組員 1 已爬取、組員 2 已清理、組員 3 已處理影片」的完整情境，
另外對 repo 內的真實資料做一次冒煙測試。
"""
import csv
import json
import tempfile
import unittest
from pathlib import Path

from crawler.kb_analysis import TextTools, classify, extract_keywords, find_duplicates, transcript_noise
from crawler.kb_schema import REQUIRED_FIELDS, youtube_id
from crawler.kb_search import search
from crawler.knowledge_builder import build
from crawler.statistics_report import compute
from crawler.validator import validate

ROOT = Path(__file__).resolve().parent.parent
URL_FIELDS = ['id', 'url', 'type', 'origin', 'title_hint', 'topic', 'publisher', 'enabled', 'notes',
              'geo_scope', 'source_role', 'review_status', 'evidence', 'verified_at']
LIGHTHOUSE = ("白沙岬燈塔位於桃園市觀音區，日治時期明治三十四年完工，是桃園唯一的燈塔。"
              "燈塔周邊有防風林與海岸沙丘，二戰後受損重建，2021年指定為國定古蹟，是重要的文化資產。")
TEMPLE = ("甘泉寺位於觀音區，供奉石觀音，是觀音地名的由來。相傳清代農民在溪中拾得觀音形石頭，"
          "信眾建廟奉祀，寺旁甘泉井泉水清甜，每年農曆二月十九日觀世音誕辰有祭典，吸引許多信眾參拜。")


def write_csv(path, fields, rows):
    with open(path, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fields)
        w.writeheader()
        w.writerows(rows)


def url_row(i, url, origin='teacher', typ='web', role='content'):
    return dict(id=i, url=url, type=typ, origin=origin, title_hint='', topic='', publisher='',
                enabled='true', notes='', geo_scope='direct', source_role=role, review_status='',
                evidence='', verified_at='')


class Workspace:
    """建立一個模擬的專案資料夾。"""

    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        out = self.root / 'output'
        for d in ('articles', 'videos', 'images', 'links', 'raw_html', 'video_quality'):
            (out / d).mkdir(parents=True)
        rows = [url_row('page_001', 'https://travel.example.gov.tw/lighthouse'),
                url_row('page_002', 'https://blog.example.com/temple'),
                url_row('page_003', 'https://blocked.example.com/x'),
                url_row('page_004', 'https://down.example.com/y'),
                url_row('page_005', 'https://youtu.be/AAAAAAAAAAA?si=zz', typ='video'),
                url_row('page_006', 'https://copy.example.com/temple'),
                url_row('extra_001', 'https://raw.example.gov.tw/only-html', origin='extra'),
                url_row('extra_002', 'https://dir.example.gov.tw/list', origin='extra', role='discovery'),
                url_row('extra_003', 'https://www.youtube.com/watch?v=BBBBBBBBBBB', origin='extra', typ='video')]
        write_csv(self.root / 'urls.csv', URL_FIELDS, rows)
        write_csv(self.root / 'urls_teacher_original.csv', URL_FIELDS, [r for r in rows if r['origin'] == 'teacher'])
        t = '2026-11-01T10:00:00+08:00'
        report = [
            dict(id='page_001', source_url=rows[0]['url'], crawl_status='success', http_status='200', title='白沙岬燈塔 | 桃園觀光', crawled_at=t),
            dict(id='page_002', source_url=rows[1]['url'], crawl_status='success', http_status='200', title='甘泉寺', crawled_at=t),
            dict(id='page_003', source_url=rows[2]['url'], crawl_status='unavailable', reason='robots.txt 不允許存取', crawled_at=t),
            dict(id='page_004', source_url=rows[3]['url'], crawl_status='failed', reason='HTTP 404', http_status='404', crawled_at=t),
            dict(id='page_005', source_url=rows[4]['url'], crawl_status='pending_video', crawled_at=t),
            dict(id='page_006', source_url=rows[5]['url'], crawl_status='success', http_status='200', crawled_at=t),
            dict(id='extra_001', source_url=rows[6]['url'], crawl_status='success', http_status='200', crawled_at=t),
            dict(id='page_001_extra_01', source_url='https://travel.example.gov.tw/caota', crawl_status='success', http_status='200', crawled_at=t),
            dict(id='manual_001', source_url='https://x.example.com', crawl_status='success', crawled_at=t),
        ]
        write_csv(out / 'crawl_report.csv', ['id', 'source_url', 'crawl_status', 'reason', 'http_status', 'title', 'crawled_at'], report)
        (out / 'links' / 'page_001.json').write_text(json.dumps(
            ['https://travel.example.gov.tw/caota', 'https://travel.example.gov.tw/login', 'https://other.com/']), encoding='utf-8')
        (out / 'images' / 'page_001_image_01.jpg').write_bytes(b'\xff\xd8fake')
        (out / 'articles' / 'page_001.json').write_text(json.dumps({
            'id': 'page_001', 'title': '白沙岬燈塔', 'content': LIGHTHOUSE,
            'images': [{'file': 'page_001_image_01.jpg', 'caption': '燈塔外觀', 'source_url': 'https://travel.example.gov.tw/a.jpg'}]},
            ensure_ascii=False), encoding='utf-8')
        (out / 'articles' / 'page_002.md').write_text(
            f"---\ntitle: 觀音甘泉寺\nauthor: 小編\n---\n# 觀音甘泉寺\n\n{TEMPLE}\n", encoding='utf-8')
        (out / 'articles' / 'page_006.md').write_text(f"# 轉載\n\n{TEMPLE}\n", encoding='utf-8')
        (out / 'raw_html' / 'extra_001.html').write_text(
            "<html><body><nav>首頁 選單</nav><main><p>草漯沙丘位於觀音區海岸，是由海風與沉積作用形成的沙丘地形。</p></main>"
            "<footer>版權所有</footer></body></html>", encoding='utf-8')
        segs = [{'start': '00:00', 'end': '00:03', 'start_seconds': i * 5.0, 'end_seconds': i * 5 + 3.0, 'text': s}
                for i, s in enumerate(['今天來到觀音區', '這裡是白沙岬燈塔', '日治時期建造的燈塔', '接著去甘泉寺', '謝謝收看'])]
        video = {'id': 'video_AAAAAAAAAAA', 'type': 'video', 'title': '觀音一日遊', 'source_url': 'https://youtu.be/AAAAAAAAAAA',
                 'source_name': '測試頻道', 'content': '\n\n'.join(s['text'] for s in segs), 'links': ['https://youtu.be/AAAAAAAAAAA'],
                 'images': [{'path': 'images/v_frame_01.jpg', 'filename': 'v_frame_01.jpg', 'timestamp': '00:05', 'seconds': 5.0, 'description': '這裡是白沙岬燈塔'}],
                 'timestamps': segs, 'crawl_status': 'success (youtube_vtt (.vtt))', 'crawled_at': '2026-11-01T11:00:00+08:00',
                 'metadata': {'video_id': 'AAAAAAAAAAA', 'duration': 30, 'upload_date': '20250101'}}
        (out / 'images' / 'v_frame_01.jpg').write_bytes(b'\xff\xd8fake')
        (out / 'videos' / 'video_AAAAAAAAAAA.json').write_text(json.dumps(video, ensure_ascii=False), encoding='utf-8')
        music = dict(video, id='extra_003', source_url='https://www.youtube.com/watch?v=BBBBBBBBBBB', title='蓮花季',
                     content='\n\n'.join(['[music]'] * 10), timestamps=segs, images=[],
                     metadata={'video_id': 'BBBBBBBBBBB'})
        (out / 'videos' / 'extra_003.json').write_text(json.dumps(music, ensure_ascii=False), encoding='utf-8')
        (out / 'video_quality' / 'extra_003.json').write_text(json.dumps(
            {'id': 'extra_003', 'quality_state': 'visual_only', 'quality_reason': '歌曲字幕', 'usable_for_knowledge': False}),
            encoding='utf-8')

    def claims(self, rows):
        fields = ['claim_id', 'claim', 'verdict', 'conclusion', 'role', 'record_id', 'quote', 'location',
                  'source_name', 'source_url', 'authority', 'finding', 'checked_by', 'checked_at']
        (self.root / 'report').mkdir(exist_ok=True)
        write_csv(self.root / 'report' / 'source_verification.csv', fields,
                  [{k: r.get(k, '') for k in fields} for r in rows])

    def close(self):
        self.tmp.cleanup()


class BuilderTests(unittest.TestCase):
    def setUp(self):
        self.ws = Workspace()
        self.res = build(self.ws.root, write=True, verbose=False)
        self.by = {r['id']: r for r in self.res['records']}

    def tearDown(self):
        self.ws.close()

    def test_every_source_has_record_with_required_fields(self):
        for rid in ('page_001', 'page_002', 'page_003', 'page_004', 'page_005', 'page_006', 'extra_001', 'extra_002', 'extra_003'):
            self.assertIn(rid, self.by)
            for f in REQUIRED_FIELDS:
                self.assertIn(f, self.by[rid])
        lines = (self.ws.root / 'output' / 'index.jsonl').read_text(encoding='utf-8').splitlines()
        self.assertEqual(len(lines), len(self.res['records']))

    def test_status_layers(self):
        b = self.by
        self.assertEqual((b['page_001']['crawl_status'], b['page_001']['processing_status']), ('success', 'complete'))
        self.assertEqual(b['page_003']['crawl_status'], 'unavailable')
        self.assertIn('robots', b['page_003']['crawl_reason'])
        self.assertEqual(b['page_004']['processing_status'], 'failed')
        # 已下載但沒有清理後正文 → 部分完成，不能算成功
        self.assertEqual((b['extra_001']['crawl_status'], b['extra_001']['processing_status']), ('success', 'partial'))
        self.assertEqual(b['extra_002']['processing_status'], 'pending')

    def test_video_id_alias_and_compat_fields(self):
        v = self.by['page_005']
        self.assertEqual(v['type'], 'video')
        self.assertIn('video_AAAAAAAAAAA', v['id_aliases'])
        self.assertTrue(v['crawl_status'].startswith('success'))  # 組員 3 的頁面用 startswith('success') 判斷
        frame = v['images'][0]
        self.assertEqual(frame['filename'], 'v_frame_01.jpg')     # 保留組員 3 欄位
        self.assertEqual(frame['file'], 'images/v_frame_01.jpg')
        self.assertIn('t=5s', frame['source_url'])
        self.assertEqual(v['published_at'], '2025-01-01')

    def test_low_quality_video_excluded_from_analysis(self):
        v = self.by['extra_003']
        self.assertEqual(v['content_status'], 'low_quality')
        self.assertEqual(v['processing_status'], 'partial')
        self.assertEqual(v['keywords'], [])

    def test_articles_json_and_markdown(self):
        a = self.by['page_001']
        self.assertEqual(a['title'], '白沙岬燈塔')
        self.assertEqual(a['images'][0]['file'], 'images/page_001_image_01.jpg')
        self.assertEqual(a['images'][0]['article_id'], 'page_001')
        self.assertEqual(self.by['page_002']['author'], '小編')
        self.assertIn('甘泉井', self.by['page_002']['content'])
        self.assertTrue(any(l['relevant'] for l in a['links']))

    def test_explored_and_manual(self):
        self.assertEqual(self.by['page_001_extra_01']['parent_id'], 'page_001')
        self.assertNotIn('manual_001', self.by)

    def test_exact_duplicate_marked_not_removed(self):
        self.assertEqual(self.by['page_006']['duplicate_of'], 'page_002')
        self.assertTrue(self.by['page_006']['content'])

    def test_keywords_and_topics(self):
        a = self.by['page_001']
        self.assertTrue(3 <= len(a['keywords']) <= 5)
        for k in a['keywords']:
            self.assertIn(k, a['title'] + a['content'])
        self.assertEqual(self.by['page_002']['topics']['primary'], '宗教信仰')
        self.assertIn('evidence', a['topics'])

    def test_processing_report(self):
        with open(self.ws.root / 'output' / 'processing_report.csv', encoding='utf-8-sig') as f:
            rows = {r['id']: r for r in csv.DictReader(f)}
        self.assertEqual(rows['page_004']['processing_label'], '失敗')

    def test_fallback_raw_html_is_flagged(self):
        res = build(self.ws.root, {'fallback_raw_html': True}, write=False, verbose=False)
        rec = {r['id']: r for r in res['records']}['extra_001']
        self.assertEqual(rec['content_status'], 'fallback')
        self.assertIn('草漯沙丘', rec['content'])
        self.assertNotIn('版權所有', rec['content'])
        self.assertEqual(rec['processing_status'], 'partial')

    def test_site_snapshot_when_no_crawl_report(self):
        """crawl_report.csv 沒上 GitHub 時，改讀 site/index.html 內嵌的爬取紀錄。"""
        (self.ws.root / 'output' / 'crawl_report.csv').unlink()
        (self.ws.root / 'site').mkdir()
        rows = [{'id': 'page_003', 'url': 'https://blocked.example.com/x', 'crawl_status': 'unavailable',
                 'reason': '無法確認 robots.txt，保守停止', 'http_status': '', 'crawled_at': '2026-10-29T16:42:22+08:00'},
                {'id': 'page_004', 'url': 'https://down.example.com/y', 'crawl_status': 'failed',
                 'reason': 'HTTP 404', 'http_status': '404', 'crawled_at': '2026-10-29T16:42:25+08:00'}]
        (self.ws.root / 'site' / 'index.html').write_text(
            '<script>\nconst data=' + json.dumps(rows, ensure_ascii=False) + ';\nrender(data);</script>', encoding='utf-8')
        res = build(self.ws.root, write=False, verbose=False)
        by = {r['id']: r for r in res['records']}
        self.assertEqual(by['page_004']['crawl_status'], 'failed')
        self.assertIn('site/index.html', by['page_004']['pipeline']['fetch']['file'])
        self.assertEqual(by['page_003']['crawl_status'], 'unavailable')
        self.assertTrue(any('site/index.html' in m for m in res['log']))
        self.assertIn(('無法確認 robots.txt（保守停止）', 1), compute(res['records'], [])['failure_reasons'])

    def test_newer_article_overrides_old_failure_and_markdown_cleaned(self):
        """快照時 404、之後組員 2 重抓成功 → 採用較新的文章；Markdown 網址轉成純文字。"""
        (self.ws.root / 'output' / 'articles' / 'page_004.json').write_text(json.dumps({
            'id': 'page_004', 'title': '重新取得', 'crawled_at': '2026-11-08T10:00:00+08:00',
            'content': '## 標題\n- [導航](https://www.google.com/maps/x) 觀音區海岸有遼闊的沙灘與防風林，適合散步與觀察生態。'
                       '\n$(function () { $(\'[tab-cp]\').each(function () {});'}, ensure_ascii=False), encoding='utf-8')
        res = build(self.ws.root, write=False, verbose=False)
        rec = {r['id']: r for r in res['records']}['page_004']
        self.assertEqual(rec['crawl_status'], 'success')
        self.assertEqual(rec['pipeline']['refetched']['old_reason'], 'HTTP 404')
        self.assertNotIn('https://', rec['content'])
        self.assertIn('導航', rec['content'])
        self.assertTrue(any('程式碼' in f for f in rec['quality_flags']))

    def test_new_source_added_later_appears(self):
        """擴充性：之後在 urls.csv 新增網址，重新建置就會出現（狀態 pending）。"""
        with open(self.ws.root / 'urls.csv', 'a', encoding='utf-8', newline='') as f:
            csv.DictWriter(f, URL_FIELDS).writerow(url_row('extra_099', 'https://new.example.gov.tw/a', origin='extra'))
        res = build(self.ws.root, write=False, verbose=False)
        self.assertEqual({r['id']: r for r in res['records']}['extra_099']['processing_status'], 'pending')


class ValidatorTests(unittest.TestCase):
    def setUp(self):
        self.ws = Workspace()
        build(self.ws.root, write=True, verbose=False)

    def tearDown(self):
        self.ws.close()

    def codes(self, res, level=None):
        return {i['code'] for i in res['issues'].items if level is None or i['level'] == level}

    def test_claims_trace_quotes(self):
        gov = 'https://www.example.gov.tw/a'
        self.ws.claims([
            dict(claim_id='C1', claim='燈塔年代', verdict='已證實', conclusion='一致', role='crawled', record_id='page_001', quote='日治時期明治三十四年完工'),
            dict(claim_id='C1', role='evidence', source_name='官方', source_url=gov),
            dict(claim_id='C2', claim='影片', verdict='有衝突', conclusion='x', role='crawled', record_id='video_AAAAAAAAAAA', quote='這裡是白沙岬燈塔日治時期建造的燈塔'),
            dict(claim_id='C2', role='evidence', source_name='官方', source_url=gov),
            dict(claim_id='C3', claim='不在內容', verdict='資料不足', conclusion='x', role='crawled', record_id='page_002', quote='這句不存在'),
            dict(claim_id='C3', role='evidence', source_name='官方', source_url=gov)])
        res = validate(self.ws.root)
        traces = {c['claim_id']: c['crawled'][0]['trace'] for c in res['claims']}
        self.assertEqual(traces, {'C1': 'found', 'C2': 'found', 'C3': 'not_found'})  # C2 用別名 ID 也找得到
        self.assertEqual(res['issues'].count('error'), 0)
        self.assertIn('quote_not_found', self.codes(res, 'warning'))

    def test_rules_catch_errors(self):
        self.ws.claims([
            dict(claim_id='C1', claim='a', verdict='應該對', role='crawled', record_id='page_001', quote='燈塔'),
            dict(claim_id='C1', role='evidence', source_name='部落格', source_url='https://blog.example.com'),
            dict(claim_id='C2', claim='b', verdict='已證實', role='crawled', record_id='page_999', quote='x'),
            dict(claim_id='C2', role='evidence', source_name='部落格', source_url='https://blog.example.com')])
        res = validate(self.ws.root)
        errs = self.codes(res, 'error')
        for code in ('bad_verdict', 'weak_evidence', 'quote_no_record', 'too_few_claims'):
            self.assertIn(code, errs)

    def test_integrity_checks(self):
        idx = self.ws.root / 'output' / 'index.jsonl'
        recs = [json.loads(l) for l in idx.read_text(encoding='utf-8').splitlines()]
        recs = [r for r in recs if r['id'] != 'page_002']          # 老師網址缺漏
        recs[0]['images'][0]['source_url'] = ''                      # 圖片沒有來源
        recs[0]['keywords'] = ['不存在的詞', '燈塔', '觀音']           # 關鍵字不在正文
        recs.append(dict(recs[1]))                                   # ID 重複
        idx.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in recs), encoding='utf-8')
        res = validate(self.ws.root)
        self.assertTrue({'teacher_missing', 'image_no_source', 'duplicate_id'} <= self.codes(res, 'error'))
        self.assertIn('keyword_not_in_text', self.codes(res, 'warning'))


class AnalysisTests(unittest.TestCase):
    def test_classify_and_keywords(self):
        tools = TextTools()
        self.assertEqual(classify('甘泉寺', TEMPLE, tools.rules)['primary'], '宗教信仰')
        self.assertEqual(classify('', '今天天氣很好', tools.rules)['primary'], '其他')
        kws = extract_keywords({'a': {'title': '白沙岬燈塔', 'content': LIGHTHOUSE},
                                'b': {'title': '甘泉寺', 'content': TEMPLE}}, tools)
        self.assertIn('白沙岬燈塔', kws['a'])

    def test_near_duplicate(self):
        docs = {'a': {'title': '甘泉寺', 'content': TEMPLE},
                'b': {'title': '甘泉寺介紹', 'content': TEMPLE.replace('清甜', '甘甜') + '歡迎參觀。'},
                'c': {'title': '燈塔', 'content': LIGHTHOUSE}}
        pairs = find_duplicates(docs)
        self.assertEqual([(p['a'], p['b']) for p in pairs], [('a', 'b')])
        self.assertTrue(pairs[0]['level'].startswith('高度相似'))

    def test_transcript_noise(self):
        flags, severe = transcript_noise('\n'.join(['腮筒'] * 10 + ['觀音區', '燈塔', '沙丘']))
        self.assertTrue(severe and flags)
        self.assertEqual(transcript_noise('\n'.join(['今天到觀音', '看燈塔', '吃蓮子', '去沙丘', '回家'])), ([], False))

    def test_youtube_id(self):
        for u in ('https://youtu.be/2hbu5n9VLZY?si=x', 'https://youtube.com/shorts/2hbu5n9VLZY',
                  'https://www.youtube.com/watch?v=2hbu5n9VLZY&t=3'):
            self.assertEqual(youtube_id(u), '2hbu5n9VLZY')


class StatsAndSearchTests(unittest.TestCase):
    def test_partial_not_counted_as_complete(self):
        ws = Workspace()
        try:
            recs = build(ws.root, write=False, verbose=False)['records']
            s = compute(recs, [])
            self.assertGreater(s['processing_status']['partial'], 0)
            teacher = [r for r in recs if r['origin'] == 'teacher']
            self.assertLessEqual(s['teacher_complete_rate'], s['teacher_crawl_success_rate'])
            self.assertEqual(len(teacher), 6)
            self.assertIn(('HTTP 404', 1), s['failure_reasons'])
            hits = search(recs, '白沙岬燈塔', type_='video')
            self.assertEqual(hits[0][1]['id'], 'page_005')
            self.assertTrue(hits[0][2]['segments'])
        finally:
            ws.close()


class RealRepoSmokeTest(unittest.TestCase):
    """對 repo 內實際資料執行（不寫檔）。"""

    def test_real_repo(self):
        res = build(ROOT, write=False, verbose=False)
        by = {r['id']: r for r in res['records']}
        with open(ROOT / 'urls_teacher_original.csv', encoding='utf-8-sig') as f:
            teacher = [r['id'] for r in csv.DictReader(f)]
        self.assertEqual(len(teacher), 31)
        self.assertTrue(all(t in by for t in teacher))
        self.assertIn('video_2hbu5n9VLZY', by['page_026']['id_aliases'])
        self.assertEqual(len({r['id'] for r in res['records']}), len(res['records']))


if __name__ == '__main__':
    unittest.main()
