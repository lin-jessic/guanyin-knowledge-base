"""為靜態網站加上統一的影音分頁與原始成果說明；不改動爬蟲邏輯。"""
from __future__ import annotations

import argparse
from pathlib import Path
import re

NAV_MARK_START = '<!-- GUANYIN_VIDEO_TABS_START -->'
NAV_MARK_END = '<!-- GUANYIN_VIDEO_TABS_END -->'
CREDIT_MARK_START = '<!-- GUANYIN_ORIGINAL_VIDEO_CREDIT_START -->'
CREDIT_MARK_END = '<!-- GUANYIN_ORIGINAL_VIDEO_CREDIT_END -->'

STYLE = '''<style id="guanyin-video-tabs-style">
.guanyin-video-tabs{display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin:0 auto 14px;padding:12px 18px;max-width:1240px;font-family:system-ui,"Microsoft JhengHei",sans-serif}
.guanyin-video-tabs a{font-size:14px;display:inline-block;text-decoration:none;color:#4a4561;background:transparent;padding:9px 13px;border-radius:9px;line-height:1.4}
.guanyin-video-tabs a:hover{background:#eeeaf5;color:#413256}
.guanyin-video-tabs a[aria-current="page"]{background:#ebe4f5;color:#49326e;font-weight:700}
.guanyin-original-credit{background:#f5f4fa;color:#453e58;border-left:4px solid #8875ad;border-radius:8px;padding:13px 16px;line-height:1.8;margin:16px 0;font-size:14px}
@media(max-width:650px){.guanyin-video-tabs{gap:4px;padding:9px 10px}.guanyin-video-tabs a{font-size:13px;padding:8px 9px}}
</style>'''

NAV_LINKS = [
    ('index.html', '來源管理', 'index.html'),
    ('videos.html', '影片成果', 'videos.html'),
    ('video_quality.html', '影音分析', 'video_quality.html'),
    ('video_recovery.html', '影片成果 2', 'video_recovery.html'),
]


def strip_old_patch(html: str) -> str:
    for start, end in ((NAV_MARK_START, NAV_MARK_END), (CREDIT_MARK_START, CREDIT_MARK_END)):
        html = re.sub(re.escape(start) + r'.*?' + re.escape(end), '', html, flags=re.S)
    html = re.sub(r'<style id="guanyin-video-tabs-style">.*?</style>', '', html, flags=re.S)
    return html


def patch_page(page: Path) -> bool:
    if not page.is_file():
        return False
    html = page.read_text(encoding='utf-8-sig')
    html = strip_old_patch(html)
    if '</head>' not in html or '<body' not in html:
        print(f'略過不符合 HTML 結構的頁面：{page}')
        return False
    html = html.replace('</head>', STYLE + '</head>', 1)
    name = page.name
    # 移除各生成器的舊導覽，避免重複且維持統一名稱。
    if name == 'video_quality.html':
        html = re.sub(r'<nav\s+class=["\']nav["\'][^>]*>.*?</nav>', '', html, count=1, flags=re.S|re.I)
    elif name == 'videos.html':
        html = re.sub(r'<a\s+class=["\']back["\']\s+href=["\']index\.html["\'][^>]*>.*?</a>', '', html, count=1, flags=re.S|re.I)
    elif name == 'video_recovery.html':
        html = re.sub(r'<a\s+href=["\']index\.html["\'][^>]*>返回首頁</a>', '', html, count=1, flags=re.S|re.I)
    tabs = ''.join(
        f'<a href="{link}"' + (' aria-current="page"' if name == active else '') + f'>{label}</a>'
        for link, label, active in NAV_LINKS
    )
    nav = f'{NAV_MARK_START}<nav class="guanyin-video-tabs" aria-label="網站主要分頁">{tabs}</nav>{NAV_MARK_END}'
    html = re.sub(r'(<body\b[^>]*>)', lambda m: m.group(1) + nav, html, count=1, flags=re.I)
    if name == 'videos.html':
        credit = (CREDIT_MARK_START +
            '<div class="guanyin-original-credit"><strong>原始影片擷取技術成果</strong>：'
            '本頁完整保留負責影片擷取組員原有的技術成果與輸出資料。'
            '我新增的字幕、OCR、音訊分類及整理流程獨立放在「影音分析」與「影片成果 2」，'
            '沒有修改或覆蓋原本組員的影片擷取技術及原始成果。</div>' + CREDIT_MARK_END)
        # 插入標題之後，讓說明醒目且不覆蓋既有成果
        if re.search(r'</h1>', html, re.I):
            html = re.sub(r'</h1>', lambda m: m.group(0) + credit, html, count=1, flags=re.I)
        else:
            html = html.replace(NAV_MARK_END, NAV_MARK_END + credit, 1)
    page.write_text(html, encoding='utf-8')
    return True


def main() -> None:
    p = argparse.ArgumentParser(description='同步原始影片成果、影音分析、影片成果 2 分頁')
    p.add_argument('--site', default='site', help='靜態網頁資料夾')
    args = p.parse_args()
    site = Path(args.site)
    files = ['index.html', 'videos.html', 'video_quality.html', 'video_recovery.html']
    updated = []
    for filename in files:
        if patch_page(site / filename):
            updated.append(filename)
        else:
            print(f'尚未建立：{site / filename}')
    print(f'已同步 {len(updated)} 頁導覽：' + ', '.join(updated))
    print('原始影片成果由組員的原程式產生；本程式只調整 HTML 顯示。')


if __name__ == '__main__':
    main()
