# 觀音地方學｜地圖、爬取資料與手機掃碼（2026-11-09）

這是對現有網站的**增量修補**。以 `完.zip` 為基礎，只替換 ZIP 內同名新增網站檔案；**勿覆蓋或刪除 crawler/、output/、urls.csv、site/ 原有四位組員成果**。

## 更新內容

1. `frontend/templates/map.html`：修正 Leaflet 地圖圖磚散亂問題（結構性 CSS 備援、容器尺寸、地圖縮放、地點列表），支援以主題篩選、點標記顯示地方研究資料。
2. `backend/store.py`：相容既有 SQLite 資料庫，增設地點描述、關鍵詞與座標說明，預載 **三個有官方座標來源** 的地點／調查點（白沙岬燈塔、甘泉寺、草漯沙丘地景調查點）。保留原本資料與管理員編輯。
3. 地點會使用現有 `output/index.jsonl`、`output/articles/*.json`、`output/videos/*.json` 的入庫資料做文字關聯，展示資料 ID、文章標題、影片等；**關聯僅為文字檢索結果，並非人工查證**。
4. `frontend/templates/videos_public.html`：YouTube 原始影片縮圖（由 YouTube 伺服器載入），點擊播放嵌入內容；已授權的本機照片也會顯示。
5. `backend/app.py`：資料索引提供已審核照片，新增地點時可填「關聯關鍵詞」與「故事簡介」。
6. `share_lan.py`：生成本機 QR Code，用臨時 token + 同 Wi-Fi 讀取唯讀前台，封鎖後台路由，關掉程式立即停止分享。管理帳密不寫入 QR。

## 安裝（用 GitHub Desktop 的 VS Code 專案根目錄）

```cmd
py -3.12 -m pip install -r requirements-website.txt
py -3.12 -m pip install "qrcode[pil]"
py -3.12 -m backend.app
```

電腦開 `http://127.0.0.1:5000/map`。**請在這個指令執行時查看頁面**，不要再用舊的 `python -m http.server`。

若不見標記，回 `設定` 登入，按重新匯入資料（`/settings/reimport`）；再回地圖強制重新載入 `Ctrl+Shift+R`。地點上的相關文章或影片需要 `output/` 實際存在且已同步入庫。

## 圖片

- 影片縮圖用 YouTube 原始縮圖網址，播放時由 YouTube 提供嵌入影片。
- 文章照片在 `output/images/`；與 `output/articles/*.json` 的 `images[].file` 對應。
- 為避免著作權風險，**原圖在前台預設不公開**。到 `設定 → 圖片授權管理`，核對原圖使用權利後，逐張輸入例如 `images/extra_001_image_01.jpg` 並設為「已人工確認授權並允許公開」。之後相關來源與地圖卡片會顯示該圖。
- 管理後台的 `/settings/images` 可查看爬取圖片，不會自動把它們變成正式公開圖片。

## 手機 QR Code（不發布到 GitHub Pages，也不建立公開網址）

保持電腦在同一個 Wi-Fi / 可互通 LAN，**另外**開新終端機：

```cmd
py -3.12 share_lan.py
```

終端機顯示手機網址，且建立 `storage/lan_share_qr.png`。用電腦開 PNG 展示，讓手機相機掃描。網址只有啟動本次分享時有效；分享者拿到連結仍能在分享期間存取，**QR 是訪問憑證，不是身分驗證**。手機可以閱讀前台，但 `/settings`、非 GET/HEAD 操作會被拒絕。分享結束按 `Ctrl+C`。

### 特別注意

- 若手機連不上：Windows 防火牆應只允許「私人網路」的 TCP 5050；兩台裝置不能在隔離訪客 Wi-Fi。不要關閉整個防火牆。
- 不用 `localhost` 或 `127.0.0.1` 的 QR Code：手機上的這些地址代表手機自己。
- 不要做路由器 Port Forwarding、DMZ、公開 Cloudflare Tunnel；這些會改變「不公開」的條件。
- 學校 Wi-Fi 可能啟用 AP 隔離；此時請改用手機熱點讓電腦與手機加入同一個可互通網路，或換成可信任的私人 LAN。
- 因為目前 GitHub Repository 是 **public**，程式庫與其中已提交的原始檔案，並不會因為這個 QR 方案而變私密。它只是「網站服務不主動公開部署」。
- QR 產生檔不要提交到 GitHub；含一次性 token。建議 `.gitignore` 包含 `storage/`。
- 地圖與 YouTube 縮圖需要手機連線到網際網路。OSM 圖磚服務禁止大量預先下載，需保留署名。

## 官方法定座標參考

- 白沙岬燈塔：國家文化記憶庫，25.041313,121.076243；資料網址：`https://tcmb.culture.tw/zh-tw/detail?id=113634&indexCode=Culture_Place`。
- 觀音甘泉寺：客家委員會，25.036864,121.081665；`https://cloud.hakka.gov.tw/Details?p=64716&pid=279528`。
- 草漯沙丘地景登錄調查點：臺灣地景保育網，25.07074905,121.1169979；此座標在大園區，不是沙丘面狀範圍。`https://landscape.forest.gov.tw/Front/land_search/Landscape.aspx?Sn=116&id=kVsq7hIIvoI%3D`。

如果既有 SQLite 已存在，啟動時會自動增加缺少的欄位並保留既有地點及審稿資料。資料爬取和審稿程式不會因此重跑或被覆寫。
