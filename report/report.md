# 任務 2／3：正文清理與圖片工程

本次整合把 `crawler.article_parser` 接到 `crawler.main` 的 web 來源流程。HTTP
取得成功後，程式會先寫入 `output/raw_html/`，再從可信的 `article`、`main` 或
文章內容容器清理正文；導覽列、頁首／頁尾、側欄、廣告、Cookie、社群分享與
推薦／輪播區塊會在 DOM 階段移除。標題、段落、條列與表格轉成 Markdown。

圖片工程採「候選縮小後下載」策略，而不是下載整個網頁再人工刪除：

1. 依 `data-src`、`data-original`、`data-lazy-src`、`data-url`、`srcset`、`src` 順序解析 lazy-loading URL。
   同時遵守 HTML `<base href>`，並以頁面 Referer／瀏覽器型 headers 下載跨網域圖片。
2. 在正文容器內排除 logo、icon、avatar、banner、廣告／追蹤／社群關鍵字、SVG／GIF／ICO，以及推薦輪播和廣告主機。
3. 下載後以 Pillow 檢查至少 150×150、非極端長寬比，並以 MD5 去重，再轉存成 `output/images/{id}_image_XX.jpg`。
4. 圖片會插回原本 HTML 位置；JSON 同時記錄 `file`、`source_url`、`caption`、`context_paragraph`、尺寸與 hash。

輸出檔案為 `output/articles/{id}.json`、`output/articles/{id}.md`。若遇到
Cloudflare／人機驗證頁、動態空殼，程式會先嘗試 Selenium headless Chrome；仍無法取得時，會標記
`processing_status`／`processing_reason`，保留 `images: []`，不使用其他頁面的圖片替代。
需要瀏覽器渲染的網站可將 Selenium 的 `page_source` 傳入同一 parser 後再寫出檔案。

## 驗證

```powershell
py -3.12 -m unittest tests.test_article_parser -v
py -3.12 -m unittest discover -s tests -p "test_*.py"
```

最近一次檢查 `urls.csv` 的 67 筆一般網頁時，66 筆完成正文處理，23 筆使用了瀏覽器
fallback，1 筆仍被 Anti-DDoS 防護頁拒絕（`extra_004`）。

`report/screenshots/` 預留三種網站類型（政府／觀光、新聞、部落格）的原始頁面與
清理後 Markdown 對照圖。截圖必須在實際允許存取並完成渲染後產生；本 repo 不以
合成畫面冒充網站截圖。
