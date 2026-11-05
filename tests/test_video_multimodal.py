import json
import tempfile
import unittest
from pathlib import Path
from crawler.video_multimodal import select_subtitles,apply_manual_corrections, music_overlap,analyze
from crawler.video_multimodal_site import build

class Quality(unittest.TestCase):
    def test_music_vtt_excluded(self):
        rows=[{'text':'[music]','start_seconds':0,'end_seconds':5},
              {'text':'baby one by one [singing]','start_seconds':5,'end_seconds':8}]*5
        src,good,bad,stat=select_subtitles({'timestamps':rows,'crawl_status':'success (youtube_vtt (.vtt))'},manual_mode='music_only')
        self.assertEqual(src,'youtube_cc');self.assertEqual(len(good),0);self.assertEqual(len(bad),10)
    def test_chinese_preserved_even_with_music_region(self):
        rows=[{'text':'草漯沙丘','start_seconds':1,'end_seconds':3}]
        a=[{'type':'music','start_seconds':0,'end_seconds':5}]
        _,good,bad,_=select_subtitles({'timestamps':rows,'crawl_status':'success (whisper (base))'},a)
        self.assertEqual(len(good),1)
    def test_manual_fixes(self):
        rows=[{'source':'whisper','text':'師妹水庫','start_seconds':5}]
        result,n=apply_manual_corrections(rows,[{'source':'whisper','start_seconds':5,'text':'石門水庫'}])
        self.assertEqual(n,1);self.assertEqual(result[0]['original_text'],'師妹水庫')
    def test_pipeline_and_html(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for sub in ['output/videos','output/images','data','site']: (root/sub).mkdir(parents=True,exist_ok=True)
            (root/'urls.csv').write_text('id,type,url,title_hint\nextra_043,video,https://www.youtube.com/watch?v=yL4ZMN3SAeE,Music video\n',encoding='utf-8')
            (root/'data/video_quality_rules.json').write_text(json.dumps({'extra_043':{'mode':'music_only'}}),encoding='utf-8')
            obj={'id':'extra_043','type':'video','title':'Music video','source_url':'https://www.youtube.com/watch?v=yL4ZMN3SAeE',
                 'crawl_status':'success (youtube_vtt (.vtt))',
                 'timestamps':[{'start_seconds':0,'end_seconds':3,'text':'[music]'}],
                 'metadata':{'duration':70},'images':[]}
            (root/'output/videos/extra_043.json').write_text(json.dumps(obj),encoding='utf-8')
            res=analyze(root)
            self.assertEqual(res[0]['excluded'],1)
            p=build(root)
            h=p.read_text(encoding='utf-8')
            self.assertIn('多軌時間軸',h)
            self.assertNotIn('未校正',h)
            self.assertIn('Music video',h)
if __name__=='__main__': unittest.main()
