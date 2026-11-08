import io
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from crawler.article_parser import parse_article, write_article_outputs


def png_bytes(size=(400, 300), color="red"):
    stream = io.BytesIO()
    Image.new("RGB", size, color).save(stream, format="PNG")
    return stream.getvalue()


class ArticleParserTests(unittest.TestCase):
    def test_filters_noise_and_keeps_lazy_image_mapping(self):
        image = png_bytes()
        source = "https://example.org/photo.png"
        html = f"""
        <html><head><title>測試頁</title></head><body>
          <nav>導覽與廣告</nav>
          <main class="article-body">
            <h1>白沙岬燈塔</h1>
            <p>這是一段足夠長的正文，介紹白沙岬燈塔、海岸景觀與觀音地區的旅遊資訊。</p>
            <figure><img data-src="{source}" alt="燈塔外觀"><figcaption>白沙岬燈塔外觀</figcaption></figure>
            <div class="related-post"><img src="https://doubleclick.net/ad.jpg"></div>
          </main><footer>網站頁尾</footer>
        </body></html>
        """
        with tempfile.TemporaryDirectory() as tmp:
            result = parse_article(html, "https://example.org/article", "page_001", tmp,
                                   downloader=lambda _: image)
            self.assertEqual(result["content_status"], "ok")
            self.assertEqual(len(result["images"]), 1)
            self.assertIn("../images/page_001_image_01.jpg", result["content"])
            self.assertEqual(result["images"][0]["caption"], "白沙岬燈塔外觀")
            self.assertIn("介紹白沙岬燈塔", result["images"][0]["context_paragraph"])
            self.assertTrue(Path(tmp, "page_001_image_01.jpg").is_file())

    def test_small_and_duplicate_images_are_rejected(self):
        large = png_bytes()
        small = png_bytes((20, 20))
        html = """
        <main><p>這是一段足夠長的正文，讓 parser 能判斷這是文章內容而非空殼頁面。</p>
        <img data-src="https://x/one.png"><img data-src="https://x/two.png"></main>
        """
        with tempfile.TemporaryDirectory() as tmp:
            result = parse_article(html, "https://x/a", "page_002", tmp,
                                   downloader=lambda url: small if "two" in url else large)
            self.assertEqual(len(result["images"]), 1)

    def test_challenge_is_not_success(self):
        result = parse_article("<html><head><title>Just a moment...</title></head><body>Cloudflare</body></html>",
                               "https://example.org", "page_003", tempfile.mkdtemp())
        self.assertEqual(result["processing_status"], "blocked")
        self.assertEqual(result["content"], "")
        self.assertEqual(result["images"], [])

    def test_outputs_are_adapter_compatible(self):
        html = "<main><h1>文章</h1><p>這是一段足夠長的正文內容，用來測試輸出格式與 adapter 相容性。</p></main>"
        with tempfile.TemporaryDirectory() as tmp:
            result = parse_article(html, "https://example.org/a", "page_004", Path(tmp) / "images")
            write_article_outputs(result, tmp)
            self.assertTrue(Path(tmp, "articles", "page_004.json").is_file())
            self.assertTrue(Path(tmp, "articles", "page_004.md").is_file())


if __name__ == "__main__":
    unittest.main()
