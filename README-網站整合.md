# 觀音地方學｜文化教育網站整合包

本專案為 `lin-jessic/guanyin-knowledge-base` 的**增量式網站擴充**，不會覆寫四位組員的 `crawler/`、`output/`、`site/` 或任何原有網頁。

## 1. 安裝

在 GitHub Desktop 先 Pull 最新 main。**建議先新增分支** `feature/cultural-website`，以免直接覆蓋多人合作成果。

將本 ZIP 裡 `backend/`、`frontend/`、`requirements-website.txt` 複製到原 Repository **根目錄**，必須與 `crawler/`、`output/`、`urls.csv` 同一層。

PowerShell：

```powershell
py -3.12 -m pip install -r requirements-website.txt
$env:GUANYIN_ADMIN_PASSWORD = "換成自己設定的高強度密碼"
$env:GUANYIN_SECRET_KEY = "換成自己設定的隨機長字串"
py -3.12 -m backend.app
```

打開 <http://127.0.0.1:5000/>。關閉：在終端機 `Ctrl+C`。

**注意**：Flask 伺服器只綁定 `127.0.0.1`。不要把此管理後台直接透過 QR Code、臨時 Tunnel 或反向代理公開；如需跨裝置展示，請另行部署只有公開路由的版本，並確保管理路由受到網路層隔離與正式驗證。

## 2. 功能

- `/`：文化教育風格的主網站。
- `/topics`：八大正式研究主題；每個主題有子專題。
- `/research`：深入研究提綱、五個研究問題架構、證據並列、相關來源。
- `/library`：現有網頁／影音的短摘錄、原始連結與搜尋。
- `/videos`：地方影音展示，需點擊才載入 YouTube 播放器。
- `/timeline`：按既有查證紀錄整理選讀時間軸，明確標示衝突。
- `/evidence`：直接讀取 `report/source_verification.csv` 的來源查證紀錄。
- `/map`：Leaflet / OSM 互動地圖。只有後台確認來源與座標的點位才顯示。
- `/settings`：需密碼的管理中心，集中原有 `site/` 六個展示頁。
- `/settings/images`：檢視組員爬取的圖片；圖片預設不公開。
- 專題編輯：後台編輯後可發布／退回草稿，留有編輯紀錄。**沒有假裝 AI 自動查證**。
- 素材授權管理：圖片只有經人工確認授權並開啟公開後才能經 `/media/...` 讀取。

**特別說明**：現有 `site/*.html` 都只是組員原始成果，這套系統把它們放進 `/settings/legacy/...`，並不改寫爬蟲結果；既有 HTML 內某些相對路徑需要來源頁產生器自行處理。程式不提供爬蟲任意命令執行或把原始資料直接對外發布。

## 3. 更新資料

每次 Pull 最新 `main`，在本機執行：

```powershell
py -3.12 -m flask --app backend.app sync-data
```

或到設定中心按「重新同步現有爬蟲資料」。本程式使用 `output/index.jsonl`；當它缺少內容時，也會掃描 `output/articles/*.json` 與 `output/videos/*.json`，並以 `urls.csv` 補齊來源。重新匯入**不會清除人工編輯與發佈狀態**。

## 4. 已完成與仍需補強

已完成：RWD 文化風格主站、八大主題、6 個研究案例、來源交叉查證視圖、資料匯入與 SQLite、基本後台審稿/發布、來源查詢與字幕片段、地圖底圖、地圖點位的人工新增。

目前不含：自動 AI/RAG、任意爬蟲執行佇列、多人帳號權限、歷史地圖完整 GeoJSON、主題內容的人工史料校稿、影像授權確認、公開部署系統。這些不能偽裝成已完成。

## 5. 資安與資料管理

- 密碼與 secret key 從環境變數讀取；不要 Push 到公開 GitHub。
- SQLite 資料庫位於 `storage/guanyin_public.db`，建議加入 `.gitignore`：

```gitignore
storage/*.db
storage/*.db-shm
storage/*.db-wal
.env
```

- 後台是**本機單一管理員的教學展示版**，無帳號分權、登入限速或正式安全審計；不要用此版本讓外部使用者登入。
- 查證資料和圖片著作權需另行確認。
- 若要給老師手機掃 QR Code，請先製作**只有公開內容、無後台入口的獨立部署**，不要開放目前的開發伺服器。

## 6. 測試

```powershell
py -3.12 -m unittest discover -s tests -v
py -3.12 -m unittest website_tests -v
```

`website_tests.py` 只檢查主站路由、後台認證及文字呈現，不代替瀏覽器與資料內容的人工驗收。

## 7. 導覽與主網站

正式主網站入口固定為 `/`，原本 `site/index.html` 是管理成果頁，請不要再用 `py -3.12 -m http.server 8000` 把舊網頁當作正式入口。管理中心中的六個原始網頁仍保留在既有 `site/` 目錄，不需要刪除。

### 專題與影音的使用原則

- 研究提綱可以閱讀但不得視為已查證的結論。
- 正式文章須在設定中心人工編輯並發布。發布後才出現在首頁「精選研究」。
- 現有影片可連到 YouTube 原始來源，字幕使用前須人工複核。
- 圖片預設不公開：前台資料頁僅顯示經人工確認的圖片。

## 8. 開發版本檢查紀錄

已完成 Python 程式語法編譯、16 個 Jinja 模板解析、3 個資料處理單元測試。測試環境未安裝 Flask，因此三個 Flask 路由測試標記跳過；請在你已安裝 Flask 的 Windows 本機執行 `py -3.12 -m unittest website_tests -v`，並以 Chrome/Edge 逐頁驗收。
