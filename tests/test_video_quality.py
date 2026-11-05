import json
import tempfile
import unittest
from pathlib import Path
from crawler.video_quality import assess, analyze, review, subtitle_metrics
from crawler.video_quality_site import create

class QualityTests(unittest.TestCase):
    def test_music_detect(self):
        rec={'crawl_status':'success (youtube_vtt (.vtt))','timestamps':[{'text':'[music]','start_seconds':1},{'text':'baby singing [music]','start_seconds':2},{'text':'one by one','start_seconds':3}]}
        self.assertEqual(assess(rec)[0],'suspected_music')
    def test_no_subtitles(self):
        self.assertEqual(assess({'crawl_status':'success (no_subtitles)','timestamps':[]})[0],'no_transcript')
    def test_chinese_review(self):
        self.assertEqual(assess({'crawl_status':'success (whisper (base))','timestamps':[{'text':'草漯沙丘的景色很美'}]})[0],'needs_review')
    def test_non_destructive_pipeline_and_site(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'output/videos').mkdir(parents=True)
            (root/'urls.csv').write_text('id,type,url,title_hint\nextra_043,video,https://youtu.be/yL4ZMN3SAeE,觀音\n',encoding='utf-8')
            r={'id':'extra_043','type':'video','title':'觀音影片','source_url':'https://youtu.be/yL4ZMN3SAeE','crawl_status':'success (youtube_vtt (.vtt))','metadata':{'duration':120},'timestamps':[{'start':'00:01','start_seconds':1,'text':'[music]'}],'images':[]}
            raw=json.dumps(r,ensure_ascii=False)
            (root/'output/videos/extra_043.json').write_text(raw,encoding='utf-8')
            analyze(root)
            self.assertEqual((root/'output/videos/extra_043.json').read_text(encoding='utf-8'),raw)
            self.assertTrue((root/'output/video_quality/extra_043.json').exists())
            with self.assertRaises(ValueError):review(root,'extra_043','approved','')
            review(root,'extra_043','rejected','英文歌曲不是地方介紹')
            analyze(root)
            html=create(root).read_text(encoding='utf-8')
            self.assertIn('流程時間軸',html)
            self.assertIn('觀音影片',html)
            self.assertIn('rejected',html)

if __name__=='__main__':unittest.main()
