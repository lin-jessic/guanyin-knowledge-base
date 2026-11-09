"""Run with py -3.12 -m unittest website_tests -v from repository root."""
import os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from backend import store

class StoreTests(unittest.TestCase):
    def test_topic_count(self):
        from backend.content import TOPICS,FEATURES
        self.assertEqual(len(TOPICS),8)
        self.assertGreaterEqual(len(FEATURES),2)

    def test_excerpt_removes_script_like_line(self):
        self.assertNotIn('querySelector',store.safe_excerpt('document.querySelector("a")\n白沙岬燈塔是一座燈塔。'))

    def test_import_keeps_editorial_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/'output/articles').mkdir(parents=True)
            (root/'output/articles/page_001.json').write_text('{"id":"page_001","type":"web","title":"測試來源","source_url":"https://example.org/a","content":"觀音地方資料","images":[]}',encoding='utf8')
            with patch.object(store,'ROOT',root),patch.object(store,'DB',root/'storage'/'db.sqlite'):
                store.init()
                with store.connect() as db:
                    db.execute("UPDATE features SET editor_body=?,publication='published' WHERE slug='lighthouse'",('人工完成的長篇研究正文'*30,))
                store.import_outputs()
                with store.connect() as db:
                    self.assertEqual(db.execute("SELECT publication FROM features WHERE slug='lighthouse'").fetchone()[0],'published')
                    self.assertEqual(db.execute("SELECT title FROM sources WHERE id='page_001'").fetchone()[0],'測試來源')

try:
    from backend.app import app
except ImportError:
    app=None

@unittest.skipIf(app is None,'Install Flask from requirements-website.txt to run route tests')
class RouteTests(unittest.TestCase):
    def setUp(self):self.client=app.test_client()
    def test_pages(self):
        for path in ['/','/topics','/research','/library','/map','/evidence','/about']:
            with self.subTest(path=path):self.assertEqual(self.client.get(path).status_code,200)
    def test_settings_requires_login(self):
        r=self.client.get('/settings')
        self.assertEqual(r.status_code,302)
        self.assertIn('/settings/login',r.headers['Location'])
    def test_invalid_media_denied(self):self.assertEqual(self.client.get('/media/images/not-approved.jpg').status_code,404)

if __name__=='__main__':unittest.main()
