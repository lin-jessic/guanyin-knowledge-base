import unittest
from crawler.url_manager import read_rows,canonical
class RegistryTests(unittest.TestCase):
    def test_teacher_immutable_snapshot(self):
        a=read_rows('urls.csv');b=read_rows('urls_teacher_original.csv')
        self.assertEqual([(x['id'],x['url']) for x in a if x['origin']=='teacher'],[(x['id'],x['url']) for x in b])
    def test_unique_urls(self):
        a=read_rows('urls.csv');self.assertEqual(len(a),len({canonical(x['url']) for x in a}))
    def test_all_extra_are_authority(self):
        a=read_rows('urls.csv'); self.assertGreaterEqual(len(a),50)
        self.assertTrue(all(x['publisher'] for x in a if x['origin']=='extra'))
if __name__=='__main__':unittest.main()
