# Guanyin Knowledge Base｜組員 1 網址與核心爬蟲

> GitHub: https://github.com/lin-jessic/guanyin-knowledge-base  
> 期中主題：桃園市觀音區（舊稱觀音鄉）的地方知識。分工：組員 1 負責網址註冊表、HTTP 請求、超連結、錯誤日誌及系統入口。

## 資料統計與真實性

- 老師指定 `urls_teacher_original.csv`：**31 筆（不可修改，含非官方來源與 YouTube）**。
- 另行蒐集 `origin=extra`：**39 筆官方網站／官方發布的地方介紹與目錄**。
- 合計 **70 筆**，但不是 70 筆爬取成功：成功/失敗請看 `output/crawl_report.csv`。
- 注意：「官方發布的旅遊頁面」不保證內文第三方業者的歷史陳述都完全正確；仍須由組員 4 查證。
- 預設排除 `source_role=discovery` 的全市索引，不能把它們的非觀音內容誤收進知識庫。
- 部分頁面 JS 動態載入、存取限制、過期或資料版本不一致；`review_status` 只表示本次來源的人工初步核對層級，不表示 HTTP 200 或事實查證完成。

## 來源說明與範圍

- `origin=teacher`：老師原始指定來源，不等於權威資料。保留原網址，供 31 筆完整驗收。
- `origin=extra`：另行收錄官方機關網站。優先觀音區專屬頁；允許明確包含觀音的跨區保育區、路線和文化介紹。
- `geo_scope=direct`：觀音區主題或位於觀音的資料。
- `geo_scope=cross_area`：同時涵蓋觀音及其他地區。**只使用觀音段落，不能直接把整篇當成觀音史實**。
- `geo_scope=directory_only`：全市／機關目錄，僅供發現下一層網址。預設 `enabled=false`，不會直接抓取作為正式文章。
- `geo_scope=pending_review`：使用者自行加入、還沒核對範圍。
- `review_status=official_page`：有辨識到官方頁面，**不等於已查驗內容每句真偽**。
- `review_status=official_listing`：網址來自桃園觀光導覽網「觀音區」官方分類，部份細頁可能 JS 動態載入，仍須現場測試。
- `review_status=needs_page_check`：需由組員人工重新確認特定內頁內容及跨區範圍。
- `review_status=unreviewed`：新增但未經人工查核。

**特別查證案例**：觀音區公所不同頁面出現不同面積與舊行政資料；不能盲信單一數值；觀新藻礁範圍跨觀音與新屋；草漯沙丘環教認證狀態需依環境部現況確認，不可宣稱目前有效。

### 額外來源名錄

| ID | 類型 | 主題 | 出版單位 | 網址 |
|---|---|---|---|---|
| extra_001 | direct | 觀音區公所－觀音意象 | 桃園市觀音區公所 | https://www.guanyin.tycg.gov.tw/cp.aspx?Create=1&n=6874 |
| extra_002 | direct | 觀音區公所－本所沿革 | 桃園市觀音區公所 | https://www.guanyin.tycg.gov.tw/cp.aspx?n=6884 |
| extra_003 | directory_only | 觀音區公所－網站導覽 | 桃園市觀音區公所 | https://www.guanyin.tycg.gov.tw/SiteMap.aspx |
| extra_004 | direct | 桃園市政府－觀音區簡介 | 桃園市政府 | https://www.tycg.gov.tw/cp.aspx?n=38&s=476 |
| extra_005 | directory_only | 桃園觀光－各區景點 | 桃園市政府觀光旅遊局 | https://travel.tycg.gov.tw/zh-tw/Travel/ListByRegion |
| extra_006 | cross_area | 珍珠海岸－觀音段（跨區頁面） | 桃園市政府觀光旅遊局 | https://travel.tycg.gov.tw/pearl-coast/zh-tw/guide |
| extra_007 | cross_area | 桃園珍珠海岸－單車路線 | 桃園市政府觀光旅遊局 | https://travel.tycg.gov.tw/pearl-coast/zh-tw/cycling |
| extra_008 | cross_area | 珍珠海岸行程－含觀音（跨區） | 桃園市政府觀光旅遊局 | https://travel.tycg.gov.tw/zh-tw/travel/tour/343 |
| extra_009 | direct | 桃園市環保局－觀新藻礁 | 桃園市政府環境保護局 | https://tydep.tycg.gov.tw/cp.aspx?n=20010 |
| extra_010 | direct | 林業保育署－草漯沙丘地質公園 | 農業部林業及自然保育署 | https://www.forest.gov.tw/0010008 |
| extra_011 | direct | 林業保育署－草漯沙丘自然地景 | 農業部林業及自然保育署 | https://www.forest.gov.tw/0008127 |
| extra_012 | direct | 環境部－草漯沙丘環境教育場所 | 環境部 | https://neecs.moenv.gov.tw/Home/PlaceQryView?id=b3be84b9-a5f6-4d1e-a243-1eb8271dc201 |
| extra_013 | direct | 客家雲－觀音甘泉寺 | 客家委員會 | https://cloud.hakka.gov.tw/Details?p=64716&pid=279528 |
| extra_014 | cross_area | 桃園地景藝術節－觀音展區 | 桃園市政府 | https://taoyuanlandart.tycg.tw/information |
| extra_015 | direct | 農業易遊網－2026桃園蓮花季 | 農業部農村發展及水土保持署 | https://ezgo.ardswc.gov.tw/zh-tw/event/4557/ |
| extra_016 | direct | 白沙岬燈塔 | 桃園市政府觀光旅遊局 | https://travel.tycg.gov.tw/zh-tw/travel/attraction/276 |
| extra_017 | direct | 觀音自行車道 | 桃園市政府觀光旅遊局 | https://travel.tycg.gov.tw/zh-tw/travel/attraction/283 |
| extra_018 | direct | 甘泉寺 | 桃園市政府觀光旅遊局 | https://travel.tycg.gov.tw/zh-tw/travel/attraction/292 |
| extra_019 | direct | 林家古厝休閒農場 | 桃園市政府觀光旅遊局 | https://travel.tycg.gov.tw/zh-tw/travel/attraction/481 |
| extra_020 | direct | 蓮荷園休閒農場 | 桃園市政府觀光旅遊局 | https://travel.tycg.gov.tw/zh-tw/travel/attraction/483 |
| extra_021 | direct | 觀音濱海遊憩區 | 桃園市政府觀光旅遊局 | https://travel.tycg.gov.tw/zh-tw/travel/attraction/591 |
| extra_022 | direct | GFun機能生活館 | 桃園市政府觀光旅遊局 | https://travel.tycg.gov.tw/zh-tw/travel/attraction/983 |
| extra_023 | direct | 中台環境資源教育中心 | 桃園市政府觀光旅遊局 | https://travel.tycg.gov.tw/zh-tw/travel/attraction/1167 |
| extra_024 | direct | 青林農場 | 桃園市政府觀光旅遊局 | https://travel.tycg.gov.tw/zh-tw/travel/attraction/1178 |
| extra_025 | direct | 崙坪文化地景園區 | 桃園市政府觀光旅遊局 | https://travel.tycg.gov.tw/zh-tw/travel/attraction/1599 |
| extra_026 | direct | 龍貓公車站 | 桃園市政府觀光旅遊局 | https://travel.tycg.gov.tw/zh-tw/travel/attraction/2212 |
| extra_027 | direct | 觀音白玉海岸 | 桃園市政府觀光旅遊局 | https://travel.tycg.gov.tw/zh-tw/travel/attraction/2213 |
| extra_028 | direct | 觀音區多功能場館 | 桃園市政府觀光旅遊局 | https://travel.tycg.gov.tw/zh-tw/travel/attraction/2214 |
| extra_029 | direct | 水之丘主題公園 | 桃園市政府觀光旅遊局 | https://travel.tycg.gov.tw/zh-tw/travel/attraction/2231 |
| extra_030 | direct | 沿海生活實驗室 | 桃園市政府觀光旅遊局 | https://travel.tycg.gov.tw/zh-tw/travel/attraction/2394 |
| extra_031 | direct | 綠品坊與觀音循環產業 | 桃園市政府觀光旅遊局 | https://travel.tycg.gov.tw/zh-tw/consume/detail/1646 |
| extra_032 | direct | GFun機能生活館產業介紹 | 桃園市政府觀光旅遊局 | https://travel.tycg.gov.tw/zh-tw/consume/detail/1744 |
| extra_033 | direct | 大田蓮花餐廳與蓮產業 | 桃園市政府觀光旅遊局 | https://travel.tycg.gov.tw/zh-tw/consume/detail/1937 |
| extra_034 | direct | 西荷食堂 | 桃園市政府觀光旅遊局 | https://travel.tycg.gov.tw/zh-tw/consume/detail/1945 |
| extra_035 | direct | 漯食與草漯地方生活 | 桃園市政府觀光旅遊局 | https://travel.tycg.gov.tw/zh-tw/consume/detail/2836 |
| extra_036 | direct | 鼎好好客食堂 | 桃園市政府觀光旅遊局 | https://travel.tycg.gov.tw/zh-tw/consume/detail/3243 |
| extra_037 | cross_area | 觀音區四季賞蓮資訊 | 桃園市政府觀光旅遊局 | https://travel.tycg.gov.tw/zh-tw/travel/flower-viewing |
| extra_038 | direct | 觀音當地旅宿-黃金海岸 | 桃園市政府觀光旅遊局 | https://travel.tycg.gov.tw/zh-tw/accommodation/detail/307 |
| extra_039 | direct | 觀音當地旅宿-mini嵐 | 桃園市政府觀光旅遊局 | https://travel.tycg.gov.tw/zh-tw/accommodation/detail/3248 |

## Windows / VS Code 操作（在專案根目錄執行）

```powershell
# 初次安裝
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v

# 看來源
python -m crawler.url_cli list
python -m crawler.url_cli list --origin teacher
python -m crawler.url_cli list --origin extra
python -m crawler.url_cli list --origin extra --scope direct
python -m crawler.url_cli list --all

# 新增網址（網址為示意，請換成自己查核的實際觀音官方網址）
python -m crawler.url_cli add "https://example.org/guanyin" --title "新觀音來源" --topic "地方文化" --publisher "出版單位"

# 編修網址或資料欄位
python -m crawler.url_cli update extra_016 --title "修正標題" --topic "歷史文化"
python -m crawler.url_cli update extra_016 --scope direct --review official_page
python -m crawler.url_cli update extra_016 --url "https://example.org/updated"
python -m crawler.url_cli disable extra_016
python -m crawler.url_cli enable extra_016
python -m crawler.url_cli delete extra_016

# 執行
python -m crawler.main --id page_001
python -m crawler.main --id extra_001
python -m crawler.main --origin teacher
python -m crawler.main --origin extra
python -m crawler.main --resume
python -m crawler.main --retry-failed
python -m crawler.main --id extra_001 --explore --max-extra 2
python -m crawler.main --url "https://www.guanyin.tycg.gov.tw/cp.aspx?n=6884"

# 匯出給其他組員讀取的資料來源註冊表
python -m crawler.export_sources
```

> 注意：`extra_016` 是指令語法範例，不保證此 ID 正好是剛新增的資料；新增後看終端機回傳的真實 ID。老師 31 筆網址不允許永久刪除／改寫；CSV 改動前自動產生備份。CSV 中手動新增資料若需重新啟用，請先確認 `geo_scope` 與 `review_status`。

## 輸出與交接給組員

- `output/raw_html/<id>.html`：組員 2 可用於正文、圖片、Lazy Loading 分析。
- `output/links/<id>.json`：組員 1 的超連結成果，給組員 2／4 延伸分析。
- `output/crawl_report.csv`：每筆爬取結果、HTTP 狀態、錯誤原因、內容 SHA256、變更判定、時間及來源 ID。
- `output/source_registry.json`：`python -m crawler.export_sources` 匯出的來源名錄（組員 4 可使用）。
- YouTube 由組員 3 處理，爬蟲紀錄為 `pending_video`；**不能當成成功抓取字幕**。

## 組員整合約定

1. 組員 1 **不覆蓋**組員 2、3、4 檔案。每人只操作自己的 `feature/*` Branch。
2. 組員 2 從 `raw_html` 讀入，輸出 `output/articles/`、`output/images/`；需要追蹤來源時以 `id` 關聯。
3. 組員 3 用 `urls.csv` 中 `type=video` 來源，合法存取字幕與代表畫面，保存時間戳；無法存取時留原因。
4. 組員 4 整理 JSONL、去重、分類及查證；**不可直接把 `crawl_status=success` 當作內容已查證**。
5. 老師可能任選 31 筆中任何一筆現場展示，包含失敗或限制存取狀態，必須能說明失敗原因，不以虛構內容替代。

## 本版尚未保證完成的事

- 這份套件包含已整理來源和可執行程式，但**沒有宣稱已實際測試所有網站連線**。
- `--explore` 是一層同網域及關鍵字過濾的探索，不會自動批准新來源為官方或觀音專屬，需人工審查。
- 商業頁面即使收錄於官方觀光網站，介紹仍可能來自商家，需交叉查證。
- 真正的正文乾淨度、圖片合法保存、影片字幕、結構化成品是組員 2／3／4 的工作。

## 參考依據

- 老師兩份期中文件：《爬蟲作業》、《resource.20260921》；及《觀音地方學》編纂說明。
- 桃園市政府觀光導覽網「各區景點」→「觀音區」分類：https://travel.tycg.gov.tw/zh-tw/Travel/ListByRegion
- 桃園市觀音區公所：https://www.guanyin.tycg.gov.tw/
- 桃園市政府觀音區介紹：https://www.tycg.gov.tw/cp.aspx?n=38&s=476
- 桃園市政府環境保護局觀新藻礁：https://tydep.tycg.gov.tw/cp.aspx?n=20010
