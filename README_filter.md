# 來源篩選工具（組員 1）

此補丁**不改動** `urls.csv`、`urls_teacher_original.csv`、`crawler/main.py` 或其他組員模組。

從 `crawl_report.csv` 的各 ID 最新紀錄判斷：HTTP 200 且有至少 1000 bytes HTML 的網頁進入 `working`（尚須確認實際正文）；未測試、影片及內容待核對者進入 `pending`；失敗者進入 `excluded`。發現來源是 `discovery` 時保留作探索用途，不算知識文章。手動 `manual_001` 不會代替正式 ID；應用 `--id` 重跑才能形成可對應記錄。

## 執行

把 `crawler/filter_working_sources.py` 放入既有專案的 `crawler/`；原檔案不需覆蓋。在專案根目錄執行：

```powershell
py -3.12 -m crawler.filter_working_sources
```

## 輸出

- `output/filtered/urls_working.csv`：實際 HTTP 成功且有 HTML 的來源
- `output/filtered/urls_pending.csv`：未測、影片、需檢查內容
- `output/filtered/urls_excluded.csv`：已測卻失敗的來源
- `output/filtered/source_audit.csv`：所有 70 筆及篩選理由
- `output/filtered/working_registry.json`：給組員 2/4 使用的清單

老師指定 31 筆即使失敗也保留在原清單，不得只交成功清單。先跑完全數網址再篩選，避免把未測試誤判失敗。
