# Guanyin Knowledge Base｜觀音地方知識爬蟲

本專案為桃園市觀音區（舊稱觀音鄉）地方資料的多媒體爬蟲期中作業。**組員 1**負責 URL CRUD、來源清單、HTTP 請求、超連結與交接。其他組員分別處理正文圖片、影片字幕、結構化與查證。

## 網站是否必做？
老師要求的是可重現的爬蟲、JSON／Markdown、圖片／影片、來源查核、程式碼及報告，**未要求架設網站**。新增的 `site/index.html` 是**額外本機展示網站**：資料搜尋、分類、請求紀錄。不代表其他三人模組完成。

## 環境
建議 **Python 3.12**：在使用者 Windows 電腦上，3.13 對部分觀音區公所 HTTPS 憑證報錯，3.12 成功獲得 HTTP 200；不關閉 SSL 驗證。

```powershell
py -3.12 -m pip install -r requirements.txt
py -3.12 -m unittest discover -s tests -v
```

## 資料來源
- `urls_teacher_original.csv`：老師提供的原始 31 筆，不修改原始指定網址；老師來源不一定權威。
- `urls.csv`：31 筆老師來源＋39 筆額外官方候選，共 70 筆（可含跨區觀音內容）。
- 額外來源 2 筆 `source_role=discovery`：`extra_003` 觀音區公所網站導覽、`extra_005` 桃園市各區觀光目錄。目錄**不是**觀音專屬單篇資料。
- 其他額外來源有政府觀光、區公所、環境部、林業、客家、農業、桃園文化等；個別頁面是否正確、有效、具觀音內容仍應逐一實測與查證。詳見 `SOURCE_REVIEW.md`、`urls.csv` 的 `geo_scope`, `review_status`, `evidence`。
- `enabled=true` 只代表允許爬蟲嘗試，不代表成功或權威內容全部核實。

## URL 管理（新增、修改、刪除、停用）
```powershell
py -3.12 -m crawler.url_cli list --all
py -3.12 -m crawler.url_cli list --origin teacher
py -3.12 -m crawler.url_cli list --origin extra
py -3.12 -m crawler.url_cli add "https://example.org/guanyin" --title "新增資料" --topic "歷史文化" --publisher "來源單位"
py -3.12 -m crawler.url_cli update extra_040 --title "修正名稱" --topic "歷史文化"
py -3.12 -m crawler.url_cli disable extra_040
py -3.12 -m crawler.url_cli enable extra_040
py -3.12 -m crawler.url_cli delete extra_040
```
示例 ID 以實際新增的回傳值為準。修改前會備份 CSV；老師原始網址不能改 URL 或刪除。

## 爬蟲
```powershell
py -3.12 -m crawler.main --id page_001 --delay 2
py -3.12 -m crawler.main --id extra_003 --delay 2
py -3.12 -m crawler.main --origin teacher --delay 2
py -3.12 -m crawler.main --origin extra --delay 2
py -3.12 -m crawler.main --origin extra --include-discovery --delay 2
py -3.12 -m crawler.main --id extra_001 --explore --max-extra 2 --delay 2
py -3.12 -m crawler.main --resume --include-discovery
py -3.12 -m crawler.main --retry-failed --include-discovery
```
單一來源 ID 允許抓 `discovery`；批次預設排除目錄，加入 `--include-discovery` 才包含。延伸爬取設定一層及數量限制，遵守網站 robots 與使用條款；不要用 `verify=False` 取代 SSL 驗證。HTTP 200 不等於正文可用。

## 匯出交接與產生網站
```powershell
py -3.12 -m crawler.export_sources
py -3.12 -m crawler.export_sources --content-only
py -3.12 -m crawler.build_site
start site\index.html
```
新版預設**匯出全部 70 筆**至 `output/source_registry.json`；`--content-only` 才只匯出 68 筆內容候選。`build_site` 根據 `urls.csv`、`output/crawl_report.csv` 產生靜態展示頁。更新爬取紀錄後重新執行建站指令。

若要由本機 HTTP 伺服器打開：
```powershell
py -3.12 -m http.server 8000 --directory site
```
瀏覽器開啟 http://localhost:8000/ ，用 Ctrl+C 停止服務。

## 四人銜接
| 成員 | 取得檔案 | 後續責任 |
|---|---|---|
| 1 | `urls.csv`, `output/raw_html/{id}.html`, `output/links/{id}.json`, `output/crawl_report.csv` | 核心爬取與錯誤紀錄 |
| 2 | 來源 ID、HTML、Links | 清理正文、圖片／來源對應 |
| 3 | `type=video` 的 URL、來源 ID | 字幕、時間戳記、合法畫面 |
| 4 | `output/source_registry.json`, `output/crawl_report.csv` | `index.jsonl`、關鍵字、交叉查證、統計 |

目前不包含組員 2–4 的功能實作。原始 HTML、來源紀錄與影片資料不能混淆。HTTP 成功與內容清理成功應分開記錄。`manual_001` 是臨時 URL 測試 ID，不應替代正式來源 ID。

## 備註
- 檔案包含你上傳 ZIP 中已有的本地執行成果，但不代表 70 筆皆已完整爬取。
- ZIP 不含 `.git`，可放到現有工作目錄合併；不要直接取代其他人新加的程式。
- 靜態頁不會自動連線、沒有新增刪除按鈕；來源變更請用 CLI，再重新生成頁面。
