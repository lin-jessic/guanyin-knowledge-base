# 組員 4：結構化資料、查證與品質分析

對應老師**任務 5、6**：把組員 1–3 的成果整理成統一格式的知識庫（`output/index.jsonl`），
並做資料完整性檢查、重複偵測、主題分類、關鍵字、來源查證與成果統計。

> 本模組**只讀取**其他組員的輸出，不修改他們的程式與檔案。
> 統一格式保留了組員 3 影片頁面需要的欄位，`video_site`、`sync_home_video`、`video_quality` 都能照常運作。

## 快速開始

```powershell
py -3.12 -m pip install -r requirements.txt
py -3.12 -m crawler.knowledge_builder --all      # 建立知識庫 → 檢查 → 統計 → 網頁（一次完成）
py -3.12 -m crawler.kb_search 白沙岬燈塔           # 搜尋知識庫（展示用）
py -3.12 -m unittest tests.test_knowledge -v     # 組員 4 的測試
```

分步驟執行：

| 指令 | 做什麼 | 主要輸出 |
|---|---|---|
| `py -3.12 -m crawler.knowledge_builder` | 合併所有組員成果、去重、分類、關鍵字 | `output/index.jsonl`、`output/processing_report.csv`、`output/analysis/` |
| `py -3.12 -m crawler.validator` | 資料完整性檢查＋來源查證比對 | `report/validation_report.md`、`report/source_verification.md` |
| `py -3.12 -m crawler.statistics_report` | 成果統計與圖表 | `output/statistics/*.png`、`report/statistics.md` |
| `py -3.12 -m crawler.kb_search 甘泉寺 --type video` | 搜尋；影片會列出字幕時間點 | 終端機 |
| `py -3.12 -m crawler.knowledge_site` | 產生知識庫網頁，並在其他 4 頁導覽列加「知識庫」連結 | `site/knowledge.html` |

> 沒有 `py` 指令的電腦，把 `py -3.12` 換成 `python`。

### 知識庫網頁 `site/knowledge.html`

直接用瀏覽器開啟（或在其他頁面點導覽列的「知識庫」）。內容：重點數字、處理狀態、主題與關鍵字、
知識庫搜尋（影片可跳到字幕時間點）、6 筆來源查證、失敗原因。資料嵌在頁面裡，不需要網路或伺服器；
圖片讀取 `../output/images/`，所以 `site/` 和 `output/` 要放在同一個專案資料夾。

其他 4 頁只在共用導覽列末端加一個 `<a href="knowledge.html">知識庫</a>`，內容不變。
組員 3 若重跑 `sync_video_tabs` 連結會消失，再執行一次 `knowledge_site` 即可；
或在 `crawler/sync_video_tabs.py` 的 `NAV_LINKS` 加一行 `('knowledge.html', '知識庫', 'knowledge.html'),`。

建議的完整順序（四人整合後）：

```powershell
py -3.12 -m crawler.main --origin teacher --delay 2      # 組員 1：爬取
# 組員 2：正文清理 → output/articles/
# 組員 3：影片處理 → output/videos/、output/video_quality/
py -3.12 -m crawler.knowledge_builder --all              # 組員 4：整合、檢查、統計、網頁
```

組員 2 還沒完成時，可以加 `--fallback-raw-html`，先從 `output/raw_html/` 粗略取出文字。
這些內容會標記為 `fallback`（暫代），不會被統計成「完整完成」。

## 三層狀態（為什麼「下載成功」不等於「成功」）

| 欄位 | 值 | 意思 |
|---|---|---|
| `crawl_status`（老師要求） | `success` 成功／`failed` 失敗／`unavailable` 無法存取／`pending` 未處理 | 有沒有取得網頁或影片 |
| `content_status` | `ok`／`low_quality`／`fallback`／`missing`／`not_applicable` | 有沒有可用的清理後內容 |
| `processing_status`（統計用） | `complete`／`partial`／`failed`／`unavailable`／`pending` | 整體結果 |

例如網頁 HTTP 200 但組員 2 還沒清理 → `crawl_status=success`、`processing_status=partial`。
統計報告一律用 `processing_status`，所以成功率不會被高估。

## index.jsonl 欄位

老師規定的 11 個欄位都有：`id`、`type`（web／video）、`title`、`source_url`、`source_name`、`content`、
`images`、`links`、`timestamps`、`crawl_status`、`crawled_at`。另外加上：

| 欄位 | 說明 |
|---|---|
| `crawl_reason` | 失敗或無法存取的原因 |
| `content_status`、`processing_status`、`content_source` | 見上表；`content_source` 記錄內容來自哪個檔案 |
| `pipeline` | 每個階段讀了哪個檔、結果如何（可追溯） |
| `origin`、`publisher`、`geo_scope`、`source_role`、`review_status` | 來自 `urls.csv` |
| `keywords` | 3–5 個關鍵字（一定是正文中出現過的詞） |
| `topics` | 主分類、次分類、各主題分數與命中的詞 |
| `duplicate_of`、`similar_to` | 重複與相似文章（只標記、不刪除） |
| `quality_flags` | 品質提醒（跨區頁面、字幕待審核、語音辨識錯誤…） |
| `id_aliases` | 其他模組用過的 ID，例如 `video_2hbu5n9VLZY` → `page_026` |

`images` 每張圖都有 `file`（相對於 `output/`）、`caption`、`source_url`、`article_id`、`kind`
（`article_image` 或 `video_frame`）。影片畫面的 `source_url` 是可直接跳到該時間點的 YouTube 連結。

## 給組員 2、3 的資料格式約定

**組員 2**：清理後的文章放在 `output/articles/`，兩種格式擇一（JSON 優先）：

```json
// output/articles/page_001.json
{
  "id": "page_001",
  "title": "白沙岬燈塔",
  "content": "清理後的正文……",
  "author": "（若有）",
  "published_at": "（若有）",
  "images": [
    {"file": "images/page_001_image_01.jpg", "caption": "燈塔外觀", "source_url": "https://原始圖片網址"}
  ]
}
```

或 `output/articles/page_001.md`（可加 `---` front matter 寫 title／author／published_at，圖片用 `![說明](../images/檔名)`）。
**每張文章圖片都要有 `source_url`**，否則 validator 會報錯（無法追溯來源）。

**組員 3**：沿用現在的 `output/videos/{id}.json` 與 `output/video_quality/{id}.json` 即可，不用改。
建議 `id` 使用 `urls.csv` 的正式 ID（例如 `page_026`）；用了其他 ID 也會依影片網址自動對應回來。
`quality_state` 為 `visual_only`、`rejected` 等的字幕不納入分類與關鍵字；`needs_review` 仍會分析，但加上「待審核」提醒。

## 來源查證（任務 6-4、6-5）

查證紀錄在 `report/source_verification.csv`，可以用 Excel 編輯。每一列是一個「爬取敘述」或一個「查證來源」：

| 欄位 | 說明 |
|---|---|
| `claim_id`、`claim`、`verdict`、`conclusion` | 查證項目；判定只能是**已證實／資料不足／有衝突** |
| `role` | `crawled`＝爬取資料中的敘述；`evidence`＝查證來源 |
| `record_id`、`quote`、`location` | 對應知識庫的哪一筆、引用原句、位置（影片寫時間點） |
| `source_name`、`source_url`、`authority`、`finding` | 來源名稱、網址、性質（official／academic／publication／media／self_published／video）、內容 |

validator 會自動檢查：
- `quote` 是否**真的出現在**該筆爬取內容裡（文字、來源、時間點可互相對照）
- 判定「已證實」至少要有 1 筆官方或學術來源
- 至少 3 筆查證

目前已完成 6 筆（已證實 1、有衝突 4、資料不足 1），詳見 `report/source_verification.md`。重點：

| 編號 | 項目 | 判定 | 摘要 |
|---|---|---|---|
| C01 | 石觀音地名由來年代 | 有衝突 | 戶政事務所寫 1860、客家雲寫 1780；同一支影片前後也各說一個 |
| C02 | 觀音鄉改制為觀音區 | 有衝突 | 影片說 2015，戶政事務所寫 2014（民國 103 年），應採 2014 |
| C03 | 白沙岬燈塔 2021 年列國定古蹟 | 已證實 | 行政院公報文化部公告（110-05-10） |
| C04 | 白沙岬燈塔完工年 | 有衝突 | 文化部公告寫 1900 竣工，航港局、觀光署寫 1901 |
| C05 | 觀音區面積 | 有衝突 | 政府頁面有 87.98、87.9807、99.83、99.85 四種數字 |
| C06 | 草漯沙丘長度與面積 | 資料不足 | 只有影片說法，林業保育署頁面尚未取得 |

> 這些查證由 AI 協助檢索，**需要組員依《觀音地方學》G2–G4 審查關卡複核**。
> 依附件建議，其他三位組員各提供一筆查證案例時，直接在 CSV 新增列即可。

## 擴充性：來源增加時怎麼辦

| 情況 | 要做的事 |
|---|---|
| 新增網址 | 用組員 1 的 `url_cli add` 加進 `urls.csv`，重新執行 `knowledge_builder`。新網址會自動出現（未爬取前為 pending） |
| 新增主題分類 | 編輯 `data/kb/topic_rules.json`，加一個主題與關鍵詞 |
| 新地名 | 加進 `data/kb/local_terms.txt`（斷詞、關鍵字、搜尋都會用到） |
| 不想要的關鍵字 | 加進 `data/kb/stopwords.txt` |
| 新的來源「類型」（RSS、PDF、開放資料 API…） | 在 `crawler/kb_sources.py` 新增一個轉接器，builder 不用改（見下方範例） |
| 新查證案例 | 在 `report/source_verification.csv` 加列 |

新增來源類型的範例（例如之後有人做了 RSS 爬蟲，輸出 `output/rss/*.json`）：

```python
# crawler/kb_sources.py 底部
@register
class RssAdapter(SourceAdapter):
    name, order = "rss", 45          # order 決定執行順序

    def apply(self, ctx, records):
        for path in sorted((ctx.output_dir / "rss").glob("*.json")):
            data = read_json(path, {})
            rid = ctx.resolve(data.get("id", ""), data.get("url", ""), records)  # 用網址對應正式 ID
            if not rid:
                continue
            rec = records[rid]
            rec["content"] = data.get("summary", "")
            rec["content_status"] = "ok"
            rec["crawl_status"] = "success"
            rec["pipeline"]["rss"] = {"file": f"rss/{path.name}"}
```

分析也已考慮資料量成長：相似度用倒排索引先找候選，不必每兩篇都比對；關鍵字與相似度都是純 Python，不需要額外的大型套件。

## 檔案一覽

```
crawler/
├── kb_schema.py          統一格式、狀態定義
├── kb_sources.py         轉接器：urls.csv、crawl_report、articles、raw_html、videos、video_quality
├── kb_analysis.py        重複偵測、主題分類、關鍵字、字幕雜訊檢查
├── knowledge_builder.py  主程式：合併 → 分析 → 輸出
├── validator.py          完整性檢查＋來源查證
├── statistics_report.py  統計與圖表
└── kb_search.py          知識庫搜尋
data/kb/                  topic_rules.json、local_terms.txt、stopwords.txt
report/source_verification.csv   查證紀錄（人工編輯）
tests/test_knowledge.py          20 項測試（模擬完整四人流程＋真實資料冒煙測試）
```

## 期中展示建議（組員 4 段落）

1. `py -3.12 -m crawler.knowledge_builder --all`：說明三層狀態，以及「下載成功但沒有正文」為什麼算部分完成。
2. 打開 `output/index.jsonl` 的任一筆：說明欄位，展示圖片 `source_url` 與 `article_id` 的對應。
3. `py -3.12 -m crawler.kb_search 白沙岬燈塔 --type video`：展示字幕時間點可直接跳到 YouTube。
4. 打開 `report/source_verification.md`：講 C02（影片錯誤）與 C04（官方來源互相矛盾），說明為什麼不能把單一來源當定論。
5. 打開 `report/statistics.md`：成功率、失敗原因、主題分布。
