"""組員 4：產生知識庫網頁 site/knowledge.html，並在其他頁面的導覽列加上「知識庫」連結。

  python -m crawler.knowledge_site

讀取 output/index.jsonl、output/statistics/summary.json、report/source_verification.csv，
把資料嵌入單一 HTML（不需網路、不需伺服器，直接用瀏覽器打開）。

導覽列：只在 <!-- GUANYIN_VIDEO_TABS_START/END --> 之間的 <nav> 末端插入一個連結，
不改其他頁面的內容。組員 3 重跑 sync_video_tabs 後連結會消失，再執行本程式即可補回
（或請組員 3 在 sync_video_tabs.py 的 NAV_LINKS 加一行 ('knowledge.html', '知識庫', 'knowledge.html')）。
"""
from __future__ import annotations

import argparse
import html
import json
import re
from pathlib import Path

from .kb_schema import CONTENT_STATUS, PROCESSING_STATUS
from .statistics_report import compute
from .validator import load_claims, load_index, trace_quote

NAV_START, NAV_END = "<!-- GUANYIN_VIDEO_TABS_START -->", "<!-- GUANYIN_VIDEO_TABS_END -->"
TABS = [("index.html", "來源管理"), ("videos.html", "影片成果"), ("video_quality.html", "影音分析"),
        ("video_recovery.html", "影片成果 2"), ("knowledge.html", "知識庫")]
OTHER_PAGES = ["index.html", "videos.html", "video_quality.html", "video_recovery.html"]


def page_data(records: list[dict], claims: list[dict], stats: dict) -> dict:
    by_id = {r["id"]: r for r in records}
    for r in records:
        for a in r.get("id_aliases") or []:
            by_id.setdefault(a, r)
    recs = []
    for r in records:
        recs.append({
            "id": r["id"], "type": r["type"], "title": r["title"] or r["source_url"],
            "url": r["source_url"], "source": r["source_name"], "origin": r.get("origin", ""),
            "role": r.get("source_role", ""), "crawl": r["crawl_status"], "crawl_label": r["crawl_status_label"],
            "content_status": r["content_status"], "status": r["processing_status"],
            "reason": r.get("crawl_reason", ""), "content": (r.get("content") or "")[:30000],
            "keywords": r.get("keywords") or [], "topic": (r.get("topics") or {}).get("primary", ""),
            "topics2": (r.get("topics") or {}).get("secondary", []),
            "evidence": (r.get("topics") or {}).get("evidence", {}),
            "flags": r.get("quality_flags") or [], "aliases": r.get("id_aliases") or [],
            "similar": r.get("similar_to") or [], "dup": r.get("duplicate_of"),
            "crawled_at": (r.get("crawled_at") or "")[:16].replace("T", " "),
            "images": [{"file": i.get("file", ""), "caption": i.get("caption", ""),
                        "src": i.get("source_url", ""), "time": i.get("time", "")} for i in r.get("images") or []][:8],
            "segs": [[round(float(s.get("start_seconds") or 0)), s.get("text", "")]
                     for s in r.get("timestamps") or [] if s.get("text")],
        })
    cl = []
    for c in claims:
        crawled = []
        for it in c["crawled"]:
            crawled.append({**it, "trace": trace_quote(it, by_id),
                            "title": by_id.get(it["record_id"], {}).get("title", "")})
        cl.append({"id": c["claim_id"], "claim": c["claim"], "verdict": c["verdict"],
                   "conclusion": c["conclusion"], "checked": f"{c['checked_by']} {c['checked_at']}".strip(),
                   "crawled": crawled, "evidence": c["evidence"]})
    return {"records": recs, "claims": cl, "stats": stats,
            "labels": {"status": PROCESSING_STATUS, "content": CONTENT_STATUS},
            "built_at": (records[0].get("built_at") or "")[:16].replace("T", " ") if records else ""}


def nav_html(active: str) -> str:
    tabs = "".join(f'<a href="{h}"' + (' aria-current="page"' if h == active else "") + f">{l}</a>"
                   for h, l in TABS)
    return f'{NAV_START}<nav class="guanyin-video-tabs" aria-label="網站主要分頁">{tabs}</nav>{NAV_END}'


def add_nav_link(path: Path) -> str:
    """在既有頁面的導覽列末端加「知識庫」連結；已經有就不動。"""
    if not path.is_file():
        return "略過（檔案不存在）"
    text = path.read_text(encoding="utf-8-sig")
    m = re.search(re.escape(NAV_START) + r"(.*?)" + re.escape(NAV_END), text, re.S)
    if not m:
        return "略過（找不到共用導覽列）"
    if 'href="knowledge.html"' in m.group(1):
        return "已有連結"
    new_nav = m.group(1).replace("</nav>", '<a href="knowledge.html">知識庫</a></nav>', 1)
    text = text[:m.start(1)] + new_nav + text[m.end(1):]
    path.write_text(text, encoding="utf-8")
    return "已加入連結"


def build_site(root=".", output_dir="output", report_dir="report", site_dir="site", link_pages=True) -> Path:
    root = Path(root).resolve()
    out, rep, site = root / output_dir, root / report_dir, root / site_dir
    records, _ = load_index(out / "index.jsonl")
    if not records:
        raise SystemExit("沒有 output/index.jsonl，請先執行 python -m crawler.knowledge_builder")
    claims = load_claims(rep / "source_verification.csv")
    data = page_data(records, claims, compute(records, claims))
    rel = Path("..") / output_dir   # 網頁在 site/，圖片在 output/images/
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    page = (TEMPLATE.replace("__NAV__", nav_html("knowledge.html"))
            .replace("__IMG_BASE__", html.escape(rel.as_posix() + "/"))
            .replace("__DATA__", payload))
    site.mkdir(parents=True, exist_ok=True)
    path = site / "knowledge.html"
    path.write_text(page, encoding="utf-8")
    print(f"知識庫網頁完成：{path}（{len(records)} 筆資料、{len(claims)} 筆查證）")
    if link_pages:
        for name in OTHER_PAGES:
            print(f"  {name}：{add_nav_link(site / name)}")
    return path


def main(argv=None):
    p = argparse.ArgumentParser(description="組員 4：產生知識庫網頁 site/knowledge.html")
    p.add_argument("--root", default=".")
    p.add_argument("--output-dir", default="output")
    p.add_argument("--report-dir", default="report")
    p.add_argument("--site-dir", default="site")
    p.add_argument("--no-link", action="store_true", help="不要在其他頁面加導覽連結")
    a = p.parse_args(argv)
    build_site(a.root, a.output_dir, a.report_dir, a.site_dir, link_pages=not a.no_link)


# ---------------------------------------------------------------- 網頁樣板
TEMPLATE = r"""<!doctype html><html lang="zh-Hant"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>觀音地方知識｜知識庫</title>
<style>
:root{--bg:#f8f7fb;--card:#fff;--ink:#343143;--muted:#696579;--line:#e5e1eb;--soft:#f1eff6;--purple:#62587f;
--ok:#287964;--ok-bg:#e5f2ec;--warn:#8a621b;--warn-bg:#f7efdf;--bad:#9d4a43;--bad-bg:#f8e9e7;--na:#575466;--na-bg:#eeeef2;
--s-complete:#2f8f6b;--s-partial:#d9a43a;--s-unavailable:#df8357;--s-failed:#c9534b;--s-pending:#bdb9c6}
*{box-sizing:border-box}body{margin:0;background:var(--bg);font-family:system-ui,"Microsoft JhengHei",sans-serif;color:var(--ink)}
.wrap{max-width:1200px;margin:auto;padding:30px 24px 72px}.eyebrow{font-size:13px;letter-spacing:2px;color:var(--purple)}
h1{font-size:clamp(28px,4vw,40px);margin:12px 0 8px}h2{font-size:22px;margin:44px 0 6px}h3{font-size:16px;margin:0}
p{line-height:1.75;color:var(--muted)}.intro{max-width:900px}a{color:var(--purple)}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(165px,1fr));gap:12px;margin:24px 0}
.stat{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:18px 20px}
.stat strong{display:block;font-size:30px;line-height:1.3;font-variant-numeric:tabular-nums}.stat span{font-size:13px;color:var(--muted)}
.stat small{display:block;font-size:11px;color:var(--muted);margin-top:4px;line-height:1.5}
.card{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:20px 22px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.badge{display:inline-block;border-radius:100px;padding:4px 9px;font-size:11px;line-height:1.4;font-weight:650;background:var(--na-bg);color:var(--na);white-space:nowrap}
.b-complete,.b-已證實{background:var(--ok-bg);color:var(--ok)}.b-partial,.b-資料不足{background:var(--warn-bg);color:var(--warn)}
.b-failed,.b-unavailable,.b-有衝突{background:var(--bad-bg);color:var(--bad)}.b-topic{background:#ece7f6;color:#4f4270}
/* 狀態長條 */
.srow{display:grid;grid-template-columns:86px 1fr 52px;gap:10px;align-items:center;margin:10px 0;font-size:13px}
.sbar{display:flex;height:24px;gap:2px}.sbar span{display:block;height:100%;border-radius:4px;min-width:3px;position:relative}
.legend{display:flex;flex-wrap:wrap;gap:14px;font-size:12px;color:var(--muted);margin-top:12px}
.legend i{display:inline-block;width:11px;height:11px;border-radius:3px;margin-right:5px;vertical-align:-1px}
.tip{position:fixed;pointer-events:none;background:#2e2a3c;color:#fff;font-size:12px;padding:7px 10px;border-radius:8px;line-height:1.5;display:none;z-index:9;max-width:260px}
/* 長條清單 */
.hbar{display:grid;grid-template-columns:minmax(90px,150px) 1fr 34px;gap:10px;align-items:center;margin:7px 0;font-size:13px;cursor:pointer}
.hbar .track{height:14px}.hbar .fill{height:100%;background:#7c6fa3;border-radius:0 4px 4px 0}.hbar:hover .fill{background:#5d5185}
.hbar .n{color:var(--muted);font-variant-numeric:tabular-nums}.hbar.nolink{cursor:default}
/* 搜尋 */
.filters{display:grid;grid-template-columns:minmax(220px,2fr) repeat(3,minmax(130px,1fr));gap:10px;margin:18px 0 10px}
input,select{width:100%;min-width:0;border:1px solid #dcd6e6;background:#fff;border-radius:11px;padding:12px;color:var(--ink);font-size:14px}
input:focus,select:focus{outline:2px solid #c1b7d8}.count{color:var(--muted);font-size:13px;margin:8px 0 12px}
.res{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px 18px;margin-bottom:10px}
.res .top{display:flex;gap:8px;align-items:flex-start;justify-content:space-between}.res .t{font-weight:650;line-height:1.5}
.res .top>div:first-child{min-width:0;flex:1}.res,.quote,.claim p{overflow-wrap:anywhere}
.meta{font-size:12px;color:var(--muted);margin-top:4px}.kw{display:flex;flex-wrap:wrap;gap:6px;margin-top:9px}
.kw span{background:var(--soft);border-radius:7px;padding:3px 8px;font-size:12px}
.snip{font-size:13px;line-height:1.75;color:#4b475a;margin:8px 0 0;padding-left:12px;border-left:3px solid var(--line)}
mark{background:#f6e3a6;color:inherit;border-radius:3px;padding:0 2px}
.seg{font-size:13px;margin:5px 0}.seg a{font-variant-numeric:tabular-nums;text-decoration:none;font-weight:600;margin-right:6px}
.flag{font-size:12px;color:var(--warn);margin-top:6px}.imgs{display:flex;gap:8px;margin-top:10px;flex-wrap:wrap}
.imgs figure{margin:0;width:150px}.imgs img{width:150px;height:90px;object-fit:cover;border-radius:8px;background:var(--soft);display:block}
.imgs figcaption{font-size:11px;color:var(--muted);margin-top:3px;line-height:1.4}
details summary{cursor:pointer;color:var(--purple);font-size:13px;margin-top:8px}
.more{display:block;margin:14px auto 0;border:1px solid var(--line);background:#fff;border-radius:10px;padding:10px 18px;font-size:14px;cursor:pointer;color:var(--ink)}
/* 查證 */
.claim{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:20px 22px;margin-bottom:12px}
.claim .head{display:flex;gap:10px;align-items:center;flex-wrap:wrap}.claim .cid{font-weight:700;color:var(--purple)}
.quote{background:var(--soft);border-radius:10px;padding:10px 14px;margin:8px 0;font-size:14px;line-height:1.7}
.quote .src{font-size:12px;color:var(--muted);margin-top:4px}
table{border-collapse:collapse;width:100%;font-size:13px}th,td{padding:9px 10px;text-align:left;border-bottom:1px solid #efecf3;vertical-align:top;line-height:1.6}
th{background:var(--soft);color:#514b62;font-size:12px}.tbl{overflow-x:auto;border:1px solid var(--line);border-radius:12px;margin-top:10px}
.sub{font-size:12px;color:var(--muted)}.foot{margin-top:50px;font-size:12px;color:var(--muted);line-height:1.8}
__NAVCSS__
@media(max-width:760px){.grid2{grid-template-columns:1fr}.filters{grid-template-columns:1fr 1fr}.filters input{grid-column:1/-1}.wrap{padding:20px 16px 60px}}
</style></head><body>__NAV__
<main class="wrap">
<div class="eyebrow">GUANYIN LOCAL KNOWLEDGE BASE</div>
<h1>觀音地方知識｜知識庫</h1>
<p class="intro">整合四位組員的成果：來源清單與爬取紀錄、正文、影片字幕與代表畫面，統一成同一種資料格式，並做主題分類、關鍵字、重複偵測與來源查證。
<b>「取得成功」不等於「內容完成」</b>：網頁下載成功但還沒有清理後正文，會算「部分完成」。分類與關鍵字為程式推算，查證結果需經組員複核。</p>
<div class="stats" id="stats"></div>

<h2>處理狀態</h2><p>依來源分組。滑過色塊可看數量。</p>
<div class="card" id="status"></div>

<div class="grid2" style="margin-top:14px">
<div class="card"><h3>主題分類</h3><p class="sub" style="margin:4px 0 10px">點一下主題，下方搜尋會只顯示該主題</p><div id="topics"></div></div>
<div class="card"><h3>常見關鍵字</h3><p class="sub" style="margin:4px 0 10px">點一下關鍵字直接搜尋</p><div id="kws"></div></div>
</div>

<h2 id="search-h">知識庫搜尋</h2><p>搜尋標題、正文、關鍵字與影片字幕。影片會列出命中字幕的時間點，可直接跳到 YouTube 該段。</p>
<div class="filters"><input id="q" type="search" placeholder="例如：白沙岬燈塔、甘泉寺、藻礁（空白分隔多個詞）">
<select id="ft"><option value="">全部類型</option><option value="web">網頁</option><option value="video">影片</option></select>
<select id="fs"><option value="">全部狀態</option></select><select id="fp"><option value="">全部主題</option></select></div>
<div class="count" id="count"></div><div id="results"></div><button class="more" id="more" hidden>顯示更多</button>

<h2>來源查證</h2><p>每一筆都對應到爬取資料中的原句（影片附時間點），再以官方或可信來源交叉比對。✅ 表示程式已確認原句確實出現在爬取內容中。</p>
<div id="claims"></div>

<h2>失敗與無法存取</h2><div class="card" id="fails"></div>
<div class="foot" id="foot"></div>
</main><div class="tip" id="tip"></div>
<script>
const D=__DATA__, IMG="__IMG_BASE__";
const $=s=>document.querySelector(s), esc=s=>String(s??"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const SL=D.labels.status, ORDER=["complete","partial","unavailable","failed","pending"], OL={teacher:"老師指定",extra:"額外來源",discovered:"延伸探索","":"其他"};
const hms=s=>{s=Math.max(0,s|0);return [s/3600|0,(s%3600)/60|0,s%60].map(n=>String(n).padStart(2,"0")).join(":")};
const vid=u=>{const m=String(u).match(/(?:youtu\.be\/|v=|shorts\/)([\w-]{11})/);return m?m[1]:""};
const S=D.stats, pct=x=>Math.round(x*100)+"%";
// 重點數字
$("#stats").innerHTML=[[S.total,"知識庫筆數",`網頁 ${S.by_type.web||0}｜影片 ${S.by_type.video||0}`],
 [pct(S.teacher_crawl_success_rate),"老師網址取得成功率",`共 ${S.teacher_total} 筆`],
 [pct(S.teacher_complete_rate),"老師網址完整完成率","取得＋可用內容"],
 [S.article_images+S.video_frames,"圖片與影片畫面",`文章圖片 ${S.article_images}｜畫面 ${S.video_frames}`],
 [S.claims,"來源查證",Object.entries(S.verdicts).map(([k,v])=>k+" "+v).join("｜")]]
 .map(([v,l,d])=>`<div class="stat"><strong>${v}</strong><span>${l}</span><small>${esc(d)}</small></div>`).join("");
// 狀態長條（狀態色＋圖例＋滑過提示）
const tip=$("#tip");
function bindTips(root){root.querySelectorAll("[data-tip]").forEach(el=>{el.onmousemove=e=>{tip.style.display="block";tip.innerHTML=el.dataset.tip;tip.style.left=Math.min(e.clientX+14,innerWidth-270)+"px";tip.style.top=e.clientY+14+"px"};el.onmouseleave=()=>tip.style.display="none"})}
(()=>{const groups=["teacher","extra","discovered",""].filter(g=>S.by_origin[g]);
 const max=Math.max(...groups.map(g=>Object.values(S.by_origin[g]).reduce((a,b)=>a+b,0)));
 let h=groups.map(g=>{const c=S.by_origin[g],tot=Object.values(c).reduce((a,b)=>a+b,0);
  return `<div class="srow"><b>${OL[g]}</b><div class="sbar" style="width:${tot/max*100}%">${ORDER.filter(s=>c[s]).map(s=>
   `<span style="flex:${c[s]};background:var(--s-${s})" data-tip="${OL[g]}｜${SL[s]}：<b>${c[s]}</b> 筆"></span>`).join("")}</div><span class="sub">共 ${tot}</span></div>`}).join("");
 h+=`<div class="legend">${ORDER.map(s=>`<span><i style="background:var(--s-${s})"></i>${SL[s]}</span>`).join("")}</div>`;
 h+=`<details><summary>表格檢視</summary><div class="tbl"><table><tr><th>來源</th>${ORDER.map(s=>`<th>${SL[s]}</th>`).join("")}</tr>${groups.map(g=>`<tr><td>${OL[g]}</td>${ORDER.map(s=>`<td>${S.by_origin[g][s]||0}</td>`).join("")}</tr>`).join("")}</table></div></details>`;
 $("#status").innerHTML=h;bindTips($("#status"))})();
// 主題與關鍵字
function bars(el,items,onclick){const max=Math.max(1,...items.map(x=>x[1]));
 el.innerHTML=items.length?items.map(([k,v])=>`<div class="hbar" data-k="${esc(k)}"><span>${esc(k)}</span><div class="track"><div class="fill" style="width:${v/max*100}%"></div></div><span class="n">${v}</span></div>`).join(""):'<p class="sub">目前沒有資料</p>';
 el.querySelectorAll(".hbar").forEach(b=>b.onclick=()=>onclick(b.dataset.k))}
const go=()=>{render();$("#search-h").scrollIntoView({behavior:"smooth"})};
bars($("#topics"),S.topics,k=>{$("#fp").value=k;go()});
bars($("#kws"),S.top_keywords.slice(0,10),k=>{$("#q").value=k;go()});
// 篩選選單
ORDER.forEach(s=>$("#fs").insertAdjacentHTML("beforeend",`<option value="${s}">${SL[s]}</option>`));
S.topics.forEach(([t])=>$("#fp").insertAdjacentHTML("beforeend",`<option>${esc(t)}</option>`));
// 搜尋
const hl=(t,terms)=>{let s=esc(t);terms.forEach(w=>{s=s.split(esc(w)).join(`<mark>${esc(w)}</mark>`)});return s};
function snips(text,terms){const flat=text.replace(/\s+/g," "),out=[];for(const w of terms){let i=flat.indexOf(w);while(i>=0&&out.length<2){out.push((i>40?"…":"")+flat.slice(Math.max(0,i-40),i+w.length+50)+"…");i=flat.indexOf(w,i+w.length+50)}}return out}
let shown=12;
function render(reset=true){if(reset)shown=12;
 const terms=$("#q").value.trim().split(/\s+/).filter(Boolean),ft=$("#ft").value,fs=$("#fs").value,fp=$("#fp").value;
 let rows=D.records.filter(r=>(!ft||r.type===ft)&&(!fs||r.status===fs)&&(!fp||r.topic===fp||r.topics2.includes(fp))
  &&terms.every(w=>r.title.includes(w)||r.content.includes(w)||r.keywords.includes(w)||r.id===w));
 if(terms.length)rows=rows.map(r=>[terms.reduce((a,w)=>a+(r.title.split(w).length-1)*5+(r.content.split(w).length-1)+(r.keywords.includes(w)?3:0),0)*(r.content_status==="ok"?1:.5),r]).sort((a,b)=>b[0]-a[0]).map(x=>x[1]);
 $("#count").textContent=`共 ${rows.length} 筆`+(terms.length?`（搜尋：${terms.join("、")}）`:"");
 $("#results").innerHTML=rows.slice(0,shown).map(r=>card(r,terms)).join("")||'<p class="sub">沒有符合的資料</p>';
 $("#more").hidden=rows.length<=shown;}
function card(r,terms){const v=vid(r.url);
 let h=`<div class="res"><div class="top"><div><div class="t">${hl(r.title,terms)}</div>
 <div class="meta">${r.id}｜${r.type==="video"?"影片":"網頁"}｜${esc(r.source)}${r.crawled_at?"｜擷取 "+esc(r.crawled_at):""}${r.aliases.length?"｜別名 "+esc(r.aliases.join("、")):""}</div></div>
 <div style="display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end">${r.topic?`<span class="badge b-topic">${esc(r.topic)}</span>`:""}<span class="badge b-${r.status}">${SL[r.status]}</span></div></div>
 <div class="meta"><a href="${esc(r.url)}" target="_blank" rel="noopener">${esc(r.url)}</a></div>`;
 if(r.keywords.length)h+=`<div class="kw">${r.keywords.map(k=>`<span>${hl(k,terms)}</span>`).join("")}</div>`;
 if(r.reason&&["failed","unavailable"].includes(r.crawl))h+=`<div class="flag">原因：${esc(r.reason)}</div>`;
 else if(r.status==="partial")h+=`<div class="flag">${esc(D.labels.content[r.content_status]||"")}</div>`;
 if(terms.length){snips(r.content,terms).forEach(s=>h+=`<div class="snip">${hl(s,terms)}</div>`);
  if(r.type==="video")r.segs.filter(s=>terms.some(w=>s[1].includes(w))).slice(0,5).forEach(s=>h+=`<div class="seg"><a href="https://youtu.be/${v}?t=${s[0]}" target="_blank" rel="noopener">▶ ${hms(s[0])}</a>${hl(s[1],terms)}</div>`)}
 else if(r.content)h+=`<div class="snip">${esc(r.content.replace(/\s+/g," ").slice(0,110))}…</div>`;
 const hit=i=>terms.some(w=>i.caption.includes(w)), imgs=terms.length?[...r.images.filter(hit),...r.images.filter(i=>!hit(i))]:r.images;
 if(imgs.length)h+=`<div class="imgs">${imgs.slice(0,4).map(i=>`<figure><a href="${esc(i.src)}" target="_blank" rel="noopener"><img loading="lazy" src="${IMG+esc(i.file)}" alt="${esc(i.caption)}" onerror="this.parentNode.parentNode.remove()"></a><figcaption>${i.time?esc(i.time)+"　":""}${esc(i.caption).slice(0,30)}</figcaption></figure>`).join("")}</div>`;
 const extra=[...r.flags.map(f=>"⚠ "+f),...r.similar.map(s=>`相似：${s.id}（${s.level}，${s.cosine}）`),...(r.dup?[`重複：與 ${r.dup} 相同`]:[]),
  ...Object.entries(r.evidence).map(([t,w])=>`分類依據「${t}」：${w.join("、")}`)];
 if(extra.length)h+=`<details><summary>品質與分析細節（${extra.length}）</summary><div class="sub" style="line-height:1.8;margin-top:6px">${extra.map(esc).join("<br>")}</div></details>`;
 return h+"</div>"}
["#q","#ft","#fs","#fp"].forEach(s=>$(s).addEventListener("input",()=>render()));
$("#more").onclick=()=>{shown+=12;render(false)};render();
// 查證
const TR={found:"✅ 原句已在爬取內容中找到",pending:"⏳ 該筆尚無正文，待比對",not_found:"⚠️ 爬取內容中找不到這句",no_record:"❌ 找不到這筆資料",no_quote:"⚠️ 未填原句"};
const AU={official:"政府／官方",academic:"學術",publication:"出版品",media:"媒體",self_published:"當事單位自述",video:"影片",other:"其他"};
$("#claims").innerHTML=D.claims.map(c=>`<div class="claim"><div class="head"><span class="cid">${c.id}</span><h3>${esc(c.claim)}</h3><span class="badge b-${c.verdict}">${esc(c.verdict)}</span></div>
 <p style="margin:10px 0">${esc(c.conclusion)}</p>
 ${c.crawled.map(q=>`<div class="quote">${q.quote?"「"+esc(q.quote)+"」":"（未填原句）"}<div class="src"><b>${esc(q.record_id)}</b> ${esc(q.title).slice(0,32)}　${esc(q.location)}　<a href="${esc(q.source_url)}" target="_blank" rel="noopener">原始來源</a>　${TR[q.trace]||""}<br>${esc(q.finding)}</div></div>`).join("")}
 <div class="tbl"><table><tr><th style="width:38%">查證來源</th><th style="width:14%">性質</th><th>內容</th></tr>${c.evidence.map(e=>`<tr><td><a href="${esc(e.source_url)}" target="_blank" rel="noopener">${esc(e.source_name)}</a></td><td>${AU[e.authority]||esc(e.authority)}</td><td>${esc(e.finding)}</td></tr>`).join("")}</table></div>
 <div class="sub" style="margin-top:8px">查證：${esc(c.checked)}</div></div>`).join("")||'<p class="sub">尚無查證紀錄</p>';
// 失敗
const bad=D.records.filter(r=>["failed","unavailable"].includes(r.crawl));
$("#fails").innerHTML=bad.length?`<div class="tbl" style="margin:0"><table><tr><th>編號</th><th>狀態</th><th>原因</th><th>網址</th></tr>${bad.map(r=>`<tr><td>${r.id}</td><td><span class="badge b-${r.crawl}">${esc(r.crawl_label)}</span></td><td>${esc(r.reason)}</td><td><a href="${esc(r.url)}" target="_blank" rel="noopener">${esc(r.url)}</a></td></tr>`).join("")}</table></div>`
 +`<p class="sub" style="margin:10px 0 0">無法取得的來源不以其他內容替代，只保留網址、狀態與原因。</p>`:'<p class="sub">沒有失敗的來源</p>';
$("#foot").innerHTML=`資料建立時間：${esc(D.built_at)}　｜　由 <code>python -m crawler.knowledge_site</code> 從 output/index.jsonl 產生<br>
關鍵字：jieba 斷詞＋TF-IDF；主題：data/kb/topic_rules.json 規則計分；相似度：字元 3-gram 餘弦相似度。皆為程式推算，引用前請人工確認。`;
</script></body></html>"""

NAV_CSS = """.guanyin-video-tabs{display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin:0 auto 14px;padding:12px 18px;max-width:1240px;font-family:system-ui,"Microsoft JhengHei",sans-serif}
.guanyin-video-tabs a{font-size:14px;display:inline-block;text-decoration:none;color:#4a4561;background:transparent;padding:9px 13px;border-radius:9px;line-height:1.4}
.guanyin-video-tabs a:hover{background:#eeeaf5;color:#413256}
.guanyin-video-tabs a[aria-current="page"]{background:#ebe4f5;color:#49326e;font-weight:700}
@media(max-width:650px){.guanyin-video-tabs{gap:4px;padding:9px 10px}.guanyin-video-tabs a{font-size:13px;padding:8px 9px}}"""
TEMPLATE = TEMPLATE.replace("__NAVCSS__", NAV_CSS)

if __name__ == "__main__":
    main()
