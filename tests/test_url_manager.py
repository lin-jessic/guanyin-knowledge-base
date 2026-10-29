import csv
import tempfile
import unittest
from pathlib import Path
from crawler.url_manager import canonical,is_video,load_urls,add_url,update_url,delete_url,write_rows,read_rows

class TestURL(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'urls.csv'
        write_rows(self.path,[dict(id='page_001',url='https://example.org/a',type='web',origin='teacher',enabled='true')])
    def tearDown(self):self.temp.cleanup()
    def test_tracking(self):self.assertEqual(canonical('https://example.com/a?si=foo&utm_x=y'),canonical('https://example.com/a'))
    def test_video(self):self.assertTrue(is_video('https://youtu.be/abc'))
    def test_add_edit_delete(self):
        ident=add_url(self.path,'https://example.com/new',title='test')
        self.assertEqual(ident,'extra_001')
        update_url(self.path,ident,url='https://example.com/changed')
        self.assertEqual(len(load_urls(self.path)),2)
        delete_url(self.path,ident)
        self.assertEqual(len(load_urls(self.path)),1)
    def test_disable_teacher_preserved(self):
        update_url(self.path,'page_001',enabled='false')
        self.assertEqual(len(load_urls(self.path)),0)
        with self.assertRaises(ValueError):delete_url(self.path,'page_001')
    def test_duplicate(self):
        add_url(self.path,'https://example.com/new')
        with self.assertRaises(ValueError):add_url(self.path,'https://example.com/new?utm_source=abc')

if __name__=='__main__':unittest.main()
