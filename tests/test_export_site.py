import unittest,tempfile
from pathlib import Path
from crawler.build_site import build
class SiteTests(unittest.TestCase):
 def test_all_urls_in_site(self):
  with tempfile.TemporaryDirectory() as d:
   s=build(out=str(Path(d)/'index.html')).read_text(encoding='utf-8')
   self.assertIn('extra_003',s)
   self.assertIn('extra_005',s)
   self.assertIn('page_031',s)
