"""組員 4：資料完整性檢查與來源查證（任務 5、6）。

  python -m crawler.validator            # 檢查 output/index.jsonl ＋ report/source_verification.csv
  python -m crawler.validator --strict   # 有 error 時回傳錯誤碼（可放進測試或 GitHub Actions）

一、資料完整性（output/index.jsonl）
  error   ：缺少老師規定欄位、ID 重複、狀態值不合法、失敗卻沒寫原因、老師 31 筆有缺漏、
            文章圖片沒有原始網址
  warning ：圖片檔案不存在、關鍵字沒出現在正文、字幕時間順序錯誤、
            網頁已取得但尚無清理後正文
  info    ：ID 對應（例如 video_2hbu5n9VLZY → page_026）、相似文章

二、來源查證（report/source_verification.csv）
  每個 claim 要有：至少 1 筆 crawled（爬取資料中的敘述）＋ 至少 1 筆 evidence（查證來源）
  crawled 的 record_id 必須存在於知識庫，而且 quote 必須真的出現在該筆 content 裡（可追溯）
  verdict 只能是：已證實／資料不足／有衝突；「已證實」至少要有 1 筆官方或學術來源
  至少 3 個 claim（老師要求）
輸出：output/validation_report.json、report/validation_report.md、report/source_verification.md
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

from .kb_schema import (CONTENT_STATUS, CRAWL_STATUS, PROCESSING_STATUS, REQUIRED_FIELDS, TYPES,
                        VERDICTS, compact, now_iso)

AUTHORITY_LABEL = {"official": "政府機關／官方", "academic": "學術機構", "publication": "出版品",
                   "media": "新聞媒體", "self_published": "當事單位自述", "video": "影片", "other": "其他"}
STRONG_AUTHORITY = {"official", "academic", "publication"}


def guess_authority(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    if host.endswith(("gov.tw", ".gov")) or host.startswith("gazette."):
        return "official"
    if host.endswith(("edu.tw", ".edu")):
        return "academic"
    if "youtube.com" in host or "youtu.be" in host:
        return "video"
    return "other"


class Issues:
    def __init__(self):
        self.items: list[dict] = []

    def add(self, level: str, code: str, rid: str, message: str):
        self.items.append({"level": level, "code": code, "id": rid, "message": message})

    def count(self, level: str) -> int:
        return sum(1 for i in self.items if i["level"] == level)


# ---------------------------------------------------------------- 一、資料完整性
def load_index(path: Path) -> tuple[list[dict], list[str]]:
    records, bad = [], []
    if not path.is_file():
        return records, [f"找不到 {path}，請先執行 python -m crawler.knowledge_builder"]
    for n, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as e:
            bad.append(f"第 {n} 行不是合法 JSON：{e}")
    return records, bad


def teacher_ids(root: Path) -> list[str]:
    path = root / "urls_teacher_original.csv"
    if not path.is_file():
        return []
    with path.open(encoding="utf-8-sig", newline="") as f:
        return [r["id"] for r in csv.DictReader(f) if r.get("id")]


def check_records(records: list[dict], root: Path, output_dir: Path, issues: Issues) -> None:
    ids = Counter(r.get("id", "") for r in records)
    for rid, n in ids.items():
        if n > 1:
            issues.add("error", "duplicate_id", rid, f"ID 重複出現 {n} 次")
    present = set(ids)
    for rid in teacher_ids(root):
        if rid not in present:
            issues.add("error", "teacher_missing", rid, "老師指定網址沒有出現在知識庫")

    for r in records:
        rid = r.get("id", "?")
        for f in REQUIRED_FIELDS:
            if f not in r:
                issues.add("error", "missing_field", rid, f"缺少欄位 {f}")
        for f in ("images", "links", "timestamps"):
            if f in r and not isinstance(r[f], list):
                issues.add("error", "wrong_type", rid, f"{f} 應為清單")
        if r.get("type") not in TYPES:
            issues.add("error", "bad_type", rid, f"type 不合法：{r.get('type')}")
        if r.get("crawl_status") not in CRAWL_STATUS:
            issues.add("error", "bad_status", rid, f"crawl_status 不合法：{r.get('crawl_status')}")
        if r.get("content_status") not in CONTENT_STATUS:
            issues.add("error", "bad_status", rid, f"content_status 不合法：{r.get('content_status')}")
        if r.get("processing_status") not in PROCESSING_STATUS:
            issues.add("error", "bad_status", rid, f"processing_status 不合法：{r.get('processing_status')}")
        url = r.get("source_url", "")
        if not re.match(r"https?://", url or ""):
            issues.add("error", "bad_url", rid, f"source_url 不是 http(s) 網址：{url}")
        status = r.get("crawl_status")
        if status in ("failed", "unavailable") and not r.get("crawl_reason"):
            issues.add("error", "no_reason", rid, "失敗或無法存取卻沒有記錄原因")
        if status != "pending" and r.get("crawled_at"):
            try:
                datetime.fromisoformat(str(r["crawled_at"]))
            except ValueError:
                issues.add("warning", "bad_time", rid, f"crawled_at 不是 ISO 時間：{r['crawled_at']}")
        if r.get("processing_status") == "complete" and not compact(r.get("content", "")):
            issues.add("error", "empty_complete", rid, "整體狀態為完整完成，但沒有內容")
        if r.get("type") == "web" and status == "success" and r.get("content_status") == "missing" \
                and r.get("source_role") != "discovery":
            issues.add("warning", "no_clean_content", rid, "網頁已取得，但尚無組員 2 的清理後正文")
        for flag in r.get("quality_flags") or []:
            if "程式碼或網站選單殘留" in flag:
                issues.add("warning", "code_residue", rid, flag)

        # 圖片：檔案存在、有原始網址、對應到本篇
        for img in r.get("images") or []:
            f = img.get("file", "")
            if not f:
                issues.add("warning", "image_no_file", rid, "圖片紀錄沒有檔案路徑")
            elif not (output_dir / f).is_file():
                issues.add("warning", "image_missing", rid, f"找不到圖片檔 output/{f}")
            if img.get("kind") == "article_image" and not img.get("source_url"):
                issues.add("error", "image_no_source", rid, f"圖片 {f} 沒有原始網址，無法追溯來源")
            if img.get("article_id") and img["article_id"] != rid:
                issues.add("error", "image_wrong_article", rid, f"圖片 {f} 標示屬於 {img['article_id']}")

        # 關鍵字要真的出現在正文（避免 AI 推測的詞）
        text = (r.get("title") or "") + (r.get("content") or "")
        for kw in r.get("keywords") or []:
            if kw not in text:
                issues.add("warning", "keyword_not_in_text", rid, f"關鍵字「{kw}」沒有出現在標題或正文")
        if r.get("keywords") and not 3 <= len(r["keywords"]) <= 5:
            issues.add("warning", "keyword_count", rid, f"關鍵字有 {len(r['keywords'])} 個（建議 3–5 個）")

        # 影片字幕時間
        prev = -1.0
        for seg in r.get("timestamps") or []:
            try:
                s, e = float(seg.get("start_seconds", 0)), float(seg.get("end_seconds", 0))
            except (TypeError, ValueError):
                issues.add("warning", "bad_timestamp", rid, f"字幕時間格式錯誤：{seg}")
                break
            if e < s or s < prev - 0.5:
                issues.add("warning", "timestamp_order", rid, f"字幕時間順序異常（{seg.get('start')}）")
                break
            prev = s

        for alias in r.get("id_aliases") or []:
            issues.add("info", "id_alias", rid, f"其他模組使用的 ID「{alias}」已對應到 {rid}")
        for s in r.get("similar_to") or []:
            if rid < s["id"]:
                issues.add("info", "similar", rid, f"與 {s['id']} {s['level']}（相似度 {s['cosine']}）")


# ---------------------------------------------------------------- 二、來源查證
def load_claims(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    claims: dict[str, dict] = {}
    for row in rows:
        cid = (row.get("claim_id") or "").strip()
        if not cid:
            continue
        c = claims.setdefault(cid, {"claim_id": cid, "claim": "", "verdict": "", "conclusion": "",
                                    "checked_by": "", "checked_at": "", "crawled": [], "evidence": []})
        for k in ("claim", "verdict", "conclusion", "checked_by", "checked_at"):
            if row.get(k) and not c[k]:
                c[k] = row[k].strip()
        role = (row.get("role") or "").strip()
        item = {k: (row.get(k) or "").strip() for k in
                ("record_id", "quote", "location", "source_name", "source_url", "authority", "finding")}
        item["authority"] = item["authority"] or guess_authority(item["source_url"])
        (c["crawled"] if role == "crawled" else c["evidence"]).append(item)
    return list(claims.values())


def check_claims(claims: list[dict], records: list[dict], issues: Issues) -> None:
    by_id = {r["id"]: r for r in records}
    for r in records:
        for alias in r.get("id_aliases") or []:
            by_id.setdefault(alias, r)
    if len(claims) < 3:
        issues.add("error", "too_few_claims", "-", f"查證紀錄只有 {len(claims)} 筆，老師要求至少 3 筆")
    for c in claims:
        cid = c["claim_id"]
        if c["verdict"] not in VERDICTS:
            issues.add("error", "bad_verdict", cid, f"verdict「{c['verdict']}」不合法（只能是 {'／'.join(sorted(VERDICTS))}）")
        if not c["crawled"]:
            issues.add("error", "no_crawled", cid, "沒有標出爬取資料中的原始敘述（role=crawled）")
        if not c["evidence"]:
            issues.add("error", "no_evidence", cid, "沒有查證來源（role=evidence）")
        if c["verdict"] == "已證實" and not any(e["authority"] in STRONG_AUTHORITY for e in c["evidence"]):
            issues.add("error", "weak_evidence", cid, "判定「已證實」但沒有官方、學術或出版品來源")
        if not c["conclusion"]:
            issues.add("warning", "no_conclusion", cid, "沒有寫結論說明")
        for item in c["crawled"]:
            item["trace"] = trace_quote(item, by_id)
            level = {"found": None, "pending": "info", "not_found": "warning", "no_record": "error",
                     "no_quote": "warning"}[item["trace"]]
            if level:
                msg = {"pending": f"{item['record_id']} 尚無正文，等內容取得後才能比對引用原句",
                       "not_found": f"引用原句沒有出現在 {item['record_id']} 的內容中：「{item['quote'][:30]}」",
                       "no_record": f"record_id「{item['record_id']}」不在知識庫",
                       "no_quote": f"{item['record_id']} 沒有填寫引用原句（quote）"}[item["trace"]]
                issues.add(level, f"quote_{item['trace']}", cid, msg)
        for item in c["evidence"]:
            if not item["source_url"].startswith("http"):
                issues.add("error", "evidence_no_url", cid, f"查證來源「{item['source_name']}」沒有網址")


def trace_quote(item: dict, by_id: dict) -> str:
    rec = by_id.get(item["record_id"])
    if not rec:
        return "no_record"
    if not item["quote"]:
        return "no_quote"
    if not compact(rec.get("content", "")):
        return "pending"
    return "found" if compact(item["quote"]) in compact(rec["content"]) else "not_found"


# ---------------------------------------------------------------- 報告
def write_reports(root: Path, output_dir: Path, report_dir: Path, records: list[dict],
                  claims: list[dict], issues: Issues) -> None:
    data = {"checked_at": now_iso(), "records": len(records), "claims": len(claims),
            "errors": issues.count("error"), "warnings": issues.count("warning"),
            "infos": issues.count("info"), "issues": issues.items}
    (output_dir / "validation_report.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    report_dir.mkdir(parents=True, exist_ok=True)
    L = ["# 資料完整性檢查報告", "",
         f"> 檢查時間：{data['checked_at']}｜由 `python -m crawler.validator` 自動產生", "",
         f"- 知識庫筆數：{len(records)}",
         f"- 錯誤 error：**{data['errors']}**　警告 warning：{data['warnings']}　提示 info：{data['infos']}", ""]
    codes = Counter((i["level"], i["code"]) for i in issues.items)
    if codes:
        L += ["| 等級 | 類型 | 數量 |", "|---|---|---|"]
        L += [f"| {lv} | {code} | {n} |" for (lv, code), n in sorted(codes.items())]
        L.append("")
    for level, title in (("error", "錯誤（必須修正）"), ("warning", "警告"), ("info", "提示")):
        items = [i for i in issues.items if i["level"] == level]
        if items:
            L += [f"## {title}", ""] + [f"- `{i['id']}` {i['message']}" for i in items[:200]]
            if len(items) > 200:
                L.append(f"- …其餘 {len(items) - 200} 筆見 output/validation_report.json")
            L.append("")
    (report_dir / "validation_report.md").write_text("\n".join(L), encoding="utf-8")

    by_id = {r["id"]: r for r in records}
    V = ["# 來源查證紀錄", "",
         "> 由 `report/source_verification.csv` 產生。判定分為：**已證實**、**資料不足**、**有衝突**。"
         "爬取資料中的敘述以 `record_id` 對應知識庫，程式會檢查引用原句是否真的出現在爬取內容中。"
         "AI 協助檢索的結果需經組員複核，不把推測當成已確認的事實。", "",
         "| 編號 | 查證項目 | 判定 | 爬取敘述 | 查證來源 |", "|---|---|---|---|---|"]
    for c in claims:
        V.append(f"| {c['claim_id']} | {c['claim']} | **{c['verdict']}** | {len(c['crawled'])} | {len(c['evidence'])} |")
    V.append("")
    trace_label = {"found": "✅ 已在爬取內容中找到原句", "pending": "⏳ 該筆尚無正文，待比對",
                   "not_found": "⚠️ 爬取內容中找不到這句", "no_record": "❌ 找不到這筆資料", "no_quote": "⚠️ 未填原句"}
    for c in claims:
        V += [f"## {c['claim_id']}　{c['claim']}", "", f"**判定：{c['verdict']}**", "", c["conclusion"], "",
              "**爬取資料中的敘述**", ""]
        for it in c["crawled"]:
            rec = by_id.get(it["record_id"], {})
            title = rec.get("title", "")[:40]
            V.append(f"- `{it['record_id']}` {title}　{it['location']}")
            if it["quote"]:
                V.append(f"  > 「{it['quote']}」")
            V.append(f"  - {it['finding']}　{trace_label.get(it.get('trace', ''), '')}　[原始來源]({it['source_url']})")
        V += ["", "**查證來源**", "", "| 來源 | 性質 | 內容 |", "|---|---|---|"]
        for it in c["evidence"]:
            V.append(f"| [{it['source_name']}]({it['source_url']}) | {AUTHORITY_LABEL.get(it['authority'], it['authority'])} | {it['finding']} |")
        V += ["", f"<sub>查證：{c['checked_by']}　{c['checked_at']}</sub>", ""]
    (report_dir / "source_verification.md").write_text("\n".join(V), encoding="utf-8")


def validate(root=".", output_dir="output", report_dir="report", claims_file=None, write=True) -> dict:
    root = Path(root).resolve()
    out, rep = root / output_dir, root / report_dir
    issues = Issues()
    records, bad_lines = load_index(out / "index.jsonl")
    for msg in bad_lines:
        issues.add("error", "bad_json", "-", msg)
    if records:
        check_records(records, root, out, issues)
    claims = load_claims(Path(claims_file) if claims_file else rep / "source_verification.csv")
    check_claims(claims, records, issues)
    if write and out.is_dir():
        write_reports(root, out, rep, records, claims, issues)
    return {"records": records, "claims": claims, "issues": issues}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="組員 4：知識庫完整性檢查與來源查證")
    p.add_argument("--root", default=".")
    p.add_argument("--output-dir", default="output")
    p.add_argument("--report-dir", default="report")
    p.add_argument("--claims", help="查證紀錄 CSV（預設 report/source_verification.csv）")
    p.add_argument("--strict", action="store_true", help="有 error 時回傳錯誤碼 1")
    a = p.parse_args(argv)
    res = validate(a.root, a.output_dir, a.report_dir, a.claims)
    iss: Issues = res["issues"]
    print(f"檢查 {len(res['records'])} 筆資料、{len(res['claims'])} 筆查證："
          f"error {iss.count('error')}｜warning {iss.count('warning')}｜info {iss.count('info')}")
    for i in [x for x in iss.items if x["level"] == "error"][:15]:
        print(f"  ✗ {i['id']}：{i['message']}")
    verdicts = Counter(c["verdict"] for c in res["claims"])
    print("查證判定：" + "、".join(f"{k} {v}" for k, v in verdicts.items()))
    traced = Counter(it.get("trace") for c in res["claims"] for it in c["crawled"])
    print(f"引用原句比對：找到 {traced.get('found', 0)}｜待正文 {traced.get('pending', 0)}｜"
          f"找不到 {traced.get('not_found', 0)}")
    print("報告：report/validation_report.md、report/source_verification.md、output/validation_report.json")
    return 1 if a.strict and iss.count("error") else 0


if __name__ == "__main__":
    sys.exit(main())
