"""組員 4：建立結構化知識庫（任務 5、6）。

  python -m crawler.knowledge_builder              # 合併所有組員成果 → output/index.jsonl
  python -m crawler.knowledge_builder --all        # 再接著跑 validator 與 statistics_report
  python -m crawler.knowledge_builder --fallback-raw-html   # 組員 2 未完成時，暫用 raw_html 粗略文字

輸入（都是其他組員的成果，本程式只讀不改）：
  urls.csv、output/crawl_report.csv、output/links/、output/raw_html/（選用）、
  output/articles/、output/videos/、output/video_quality/
輸出：
  output/index.jsonl              每個來源一行，統一欄位（見 kb_schema.py）
  output/processing_report.csv    每個來源在「取得／內容／整體」三階段的狀態
  output/analysis/duplicates.csv  完全重複與高度相似文章
  output/analysis/topics_keywords.csv  主題分類、判斷依據與關鍵字
  output/analysis/build_log.txt   建置過程的提醒（ID 對應、缺少的檔案…）
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
from collections import Counter
from pathlib import Path

from .kb_analysis import (TextTools, classify, clean_for_analysis, code_residue, extract_keywords,
                          find_duplicates, transcript_noise)
from .kb_schema import PROCESSING_STATUS, compact, finalize_status, now_iso
from .kb_sources import ADAPTERS, BuildContext

ANALYZE_CONTENT = ("ok", "fallback")  # 這些內容狀態才納入分類、關鍵字與相似度


def sort_key(rid: str):
    """老師 31 筆 → 額外來源 → 延伸頁面，各自依編號排序。"""
    m = re.match(r"(page|extra|video)_(\d+)", rid)
    group = {"page": 0, "extra": 1}.get(m.group(1), 2) if m else 3
    return (group, int(m.group(2)) if m else 0, rid)


def build(root: str | Path = ".", options: dict | None = None, write: bool = True, verbose: bool = True) -> dict:
    root = Path(root).resolve()
    options = options or {}
    output_dir = root / options.get("output_dir", "output")
    ctx = BuildContext(root=root, urls_file=root / options.get("urls", "urls.csv"),
                       output_dir=output_dir, options=options)
    records: dict[str, dict] = {}

    # 1. 依序執行每個轉接器（新增的來源類型只要註冊 adapter，這裡不用改）
    used = []
    for cls in ADAPTERS:
        adapter = cls()
        if adapter.enabled(ctx):
            adapter.apply(ctx, records)
            used.append(adapter.name)

    built_at = now_iso()
    for rec in records.values():
        finalize_status(rec)
        rec["built_at"] = built_at
        rec["quality_flags"] = list(dict.fromkeys(rec["quality_flags"]))  # 去重保留順序

    # 2. 字幕雜訊檢查：嚴重的（例如同一句辨識錯誤佔 25% 以上）降為 low_quality
    for rec in records.values():
        if rec["type"] == "video" and rec["content"]:
            flags, severe = transcript_noise(rec["content"])
            rec["quality_flags"].extend(flags)
            if severe and rec["content_status"] == "ok":
                rec["content_status"] = "low_quality"
                rec["quality_flags"].append("字幕雜訊過多，不納入分類與關鍵字（原文仍保留）")
                finalize_status(rec)
        elif rec["type"] == "web" and (n := code_residue(rec["content"])):
            rec["quality_flags"].append(f"正文含 {n} 行程式碼或網站選單殘留（請組員 2 清理；分析時已略過）")

    # 3. 分析：只用可用內容、而且不是目錄頁
    tools = TextTools()
    docs = {rid: {"title": r["title"], "content": clean_for_analysis(r["content"])} for rid, r in records.items()
            if r["content_status"] in ANALYZE_CONTENT and r["source_role"] != "discovery" and compact(r["content"])}
    keywords = extract_keywords(docs, tools)
    for rid, d in docs.items():
        rec = records[rid]
        rec["keywords"] = keywords.get(rid, [])
        rec["topics"] = classify(d["title"], d["content"], tools.rules)
        rec["analysis_note"] = f"關鍵字：{tools.method}＋TF-IDF；分類：規則計分。皆為程式推算，引用前需人工確認。"

    pairs = find_duplicates(docs)
    for p in pairs:
        a, b = records[p["a"]], records[p["b"]]
        a["similar_to"].append({"id": p["b"], "cosine": p["cosine"], "level": p["level"]})
        b["similar_to"].append({"id": p["a"], "cosine": p["cosine"], "level": p["level"]})
        if p["level"] in ("完全重複", "幾乎相同（轉載）"):  # 標記較晚的一筆，但不刪除
            later = max(p["a"], p["b"], key=sort_key)
            records[later]["duplicate_of"] = min(p["a"], p["b"], key=sort_key)

    ordered = [records[k] for k in sorted(records, key=sort_key)]
    summary = {
        "built_at": built_at, "records": len(ordered), "adapters": used,
        "processing_status": dict(Counter(r["processing_status"] for r in ordered)),
        "analyzed": len(docs), "similar_pairs": len(pairs), "log": ctx.log,
    }
    if write:
        write_outputs(output_dir, ordered, pairs, summary)
    if verbose:
        print_summary(summary, output_dir)
    return {"records": ordered, "pairs": pairs, "summary": summary, "log": ctx.log}


# ---------------------------------------------------------------- 寫檔
def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    os.replace(tmp, path)


def write_outputs(out: Path, records: list[dict], pairs: list[dict], summary: dict) -> None:
    atomic_write(out / "index.jsonl", "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records))

    rows = []
    for r in records:
        rows.append({
            "id": r["id"], "type": r["type"], "origin": r["origin"], "source_role": r["source_role"],
            "title": r["title"], "source_url": r["source_url"], "source_name": r["source_name"],
            "crawl_status": r["crawl_status"], "crawl_status_label": r["crawl_status_label"],
            "content_status": r["content_status"], "processing_status": r["processing_status"],
            "processing_label": PROCESSING_STATUS[r["processing_status"]],
            "reason": r["crawl_reason"] or "；".join(r["quality_flags"][:2]),
            "content_chars": len(compact(r["content"])), "images": len(r["images"]),
            "links": len(r["links"]), "timestamps": len(r["timestamps"]),
            "primary_topic": r["topics"].get("primary", ""), "keywords": "、".join(r["keywords"]),
            "id_aliases": "、".join(r["id_aliases"]), "crawled_at": r["crawled_at"],
        })
    write_csv(out / "processing_report.csv", rows, list(rows[0].keys()) if rows else ["id"])

    by_id = {r["id"]: r for r in records}
    write_csv(out / "analysis" / "duplicates.csv",
              [{**p, "a_title": by_id[p["a"]]["title"], "b_title": by_id[p["b"]]["title"]} for p in pairs],
              ["a", "a_title", "b", "b_title", "cosine", "title_similarity", "level"])
    topic_rows = [{"id": r["id"], "type": r["type"], "title": r["title"],
                   "primary_topic": r["topics"]["primary"], "secondary_topics": "、".join(r["topics"]["secondary"]),
                   "keywords": "、".join(r["keywords"]),
                   "evidence": "；".join(f"{k}:{'/'.join(v)}" for k, v in r["topics"]["evidence"].items())}
                  for r in records if r["topics"]]
    write_csv(out / "analysis" / "topics_keywords.csv", topic_rows,
              ["id", "type", "title", "primary_topic", "secondary_topics", "keywords", "evidence"])
    atomic_write(out / "analysis" / "build_summary.json", json.dumps(summary, ensure_ascii=False, indent=2))
    atomic_write(out / "analysis" / "build_log.txt", "\n".join(summary["log"]) + "\n")


def print_summary(summary: dict, out: Path) -> None:
    labels = "｜".join(f"{PROCESSING_STATUS[k]} {v}" for k, v in summary["processing_status"].items())
    print(f"知識庫建立完成：{summary['records']} 筆（{labels}）")
    print(f"分析 {summary['analyzed']} 筆有內容的資料；相似文章 {summary['similar_pairs']} 對")
    print(f"使用的轉接器：{', '.join(summary['adapters'])}")
    for line in summary["log"][:12]:
        print(f"  提醒：{line}")
    if len(summary["log"]) > 12:
        print(f"  …其餘 {len(summary['log']) - 12} 則見 output/analysis/build_log.txt")
    print(f"輸出：{out / 'index.jsonl'}、{out / 'processing_report.csv'}、{out / 'analysis'}")


def main(argv=None):
    p = argparse.ArgumentParser(description="組員 4：建立觀音知識庫 index.jsonl")
    p.add_argument("--root", default=".", help="專案根目錄")
    p.add_argument("--urls", default="urls.csv")
    p.add_argument("--output-dir", default="output")
    p.add_argument("--fallback-raw-html", action="store_true",
                   help="組員 2 尚未產生 articles 時，暫用 raw_html 粗略擷取文字（會標記為 fallback）")
    p.add_argument("--min-content-chars", type=int, default=80)
    p.add_argument("--all", action="store_true",
                   help="建立後接著執行 validator、statistics_report，並產生 site/knowledge.html")
    a = p.parse_args(argv)
    options = {"urls": a.urls, "output_dir": a.output_dir, "fallback_raw_html": a.fallback_raw_html,
               "min_content_chars": a.min_content_chars}
    build(a.root, options)
    if a.all:
        from . import statistics_report, validator
        print()
        validator.main(["--root", a.root, "--output-dir", a.output_dir])
        print()
        statistics_report.main(["--root", a.root, "--output-dir", a.output_dir])
        print()
        from . import knowledge_site
        knowledge_site.main(["--root", a.root, "--output-dir", a.output_dir])


if __name__ == "__main__":
    main()
