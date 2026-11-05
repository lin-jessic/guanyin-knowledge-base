# 觀音地方知識庫｜整合網站

本套件包含四個整合後 HTML 頁面，保留原本嵌入的資料、互動程式與字幕紀錄。

## 放置方式

將本 ZIP 中四個 `.html` 檔案複製回原本的 `site/`，並**保留原有的 `site/assets/` 資料夾**（尤其 `assets/video/*.jpg`）。本次沒有收到 assets，因此它沒有打包進 ZIP。不要刪除原來的 assets。

直接開啟 `index.html`，或用 `python -m http.server 8000` 後瀏覽 `http://localhost:8000/`。

新增：四頁共用導覽列、依據現有處理紀錄撰寫的各頁技術方法與限制。原有數據與核心頁面 JavaScript 沒有修改。

注意：已產生的 HTML 不會重新執行影片分析。若原本使用產生器重新產生 HTML，可能覆蓋此次手動加入的導覽與技術說明。
