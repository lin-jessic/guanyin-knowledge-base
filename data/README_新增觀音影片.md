# 桃園觀音區｜新增 YouTube 候選來源（7 部）

本資料為 **2026-11-05** 搜尋結果整理，**沒有取代教師指定的 31 筆**，也沒有將觀音菩薩、觀音山等不屬於桃園觀音區的影片納入。

## 檔案位置

- `data/extra_video_candidates.csv`：7 筆影片、主題、頻道、來源類別與審核註記。
- `crawler/import_video_candidates.py`：從 CSV 去重匯入現有 `urls.csv`，**依 YouTube video ID** 去重，保留舊資料。既有 `url_manager.write_rows` 會建立 CSV 備份。

## 指令（Windows CMD，於 GitHub 專案根目錄）

```cmd
py -3.12 -m crawler.import_video_candidates --dry-run
py -3.12 -m crawler.import_video_candidates
py -3.12 -m crawler.url_cli list --origin extra
py -3.12 -m crawler.export_sources
py -3.12 -m crawler.filter_working_sources
py -3.12 -m crawler.build_site
py -3.12 -m crawler.video_site
py -3.12 -m crawler.sync_home_video
start site\index.html
start site\videos.html
```

如果原始清單仍為 70 筆且沒有重複，匯入後為 **77 筆**。若之前已收錄其中影片，會略過，不重複新增。`sync_home_video` 若尚未安裝可略過，則首頁影片狀態可能仍保持來源分流標籤。

## 爬取與影片處理

加入網址後，**不代表已獲得內容、字幕或影片畫面**。先執行單一影片測試：

```cmd
py -3.12 -m crawler.main --id extra_040
```

以上 `extra_040` 只是清單原有 39 筆、全部 7 筆皆新增時的第一筆預期 ID，實際請以匯入時列出的 ID 為準。影片模組可能下載大檔案或模型，並須符合平台規範及取得必要權限。

不要對所有額外來源直接執行 `--origin extra` 以便一次處理影片，除非你確定要處理的網址與合法使用範圍。

## 來源權威性

- `government_channel`：桃園市政府客家事務局；適合優先作為官方影音資料候選。
- `municipal_media`：「桃園事」發布的地方節目或藻礁影片；**目前不能僅依頻道名保證該頻道由政府官方經營**，應另核對發布者身分。
- `independent_creator`：個人旅遊／娛樂節目；可用於影像觀察與輔助分類，但歷史、地址、法定地位、營業時間必須以政府資料交叉查證。

注意 2023 年蓮花季影片屬歷史活動，2026 年影片也不能保證 2027 年營運時刻有效。跨區影片要限定觀音相關內容。

## 補充

若 `urls.csv` 匯入後變更，但網站上仍然顯示 70 筆，必須重新執行 `export_sources`、`filter_working_sources`、`build_site`、`video_site`，並重整瀏覽器。
