"""組員 4：成果統計與圖表。

  python -m crawler.statistics_report

讀 output/index.jsonl（與 report/source_verification.csv），輸出：
  output/statistics/summary.json   所有統計數字
  output/statistics/*.csv          各項統計表（Excel 可開）
  output/statistics/*.png          圖表（matplotlib）
  report/statistics.md             統計報告（含圖表與表格）

統計一律用 processing_status（整體結果），不是 crawl_status，
所以「下載成功但沒有清理後內容」會算成「部分完成」，不會被誇大成成功。
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

from .kb_schema import CRAWL_STATUS, PROCESSING_STATUS, compact
from .validator import load_claims, load_index

# 圖表配色（狀態色固定，不拿來表示一般分類）
STATUS_COLORS = {"complete": "#0ca30c", "partial": "#fab219", "unavailable": "#ec835a",
                 "failed": "#d03b3b", "pending": "#b9b7b0"}
SERIES = "#2a78d6"
INK, INK2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e4e2dc", "#fcfcfb"
ORIGIN_LABEL = {"teacher": "老師指定", "extra": "額外來源", "discovered": "延伸探索", "": "其他"}
STATUS_ORDER = ["complete", "partial", "unavailable", "failed", "pending"]


# ---------------------------------------------------------------- 計算
def short_reason(reason: str) -> str:
    """把失敗原因歸類，方便統計「常見失敗原因」。"""
    r = reason or "（未記錄）"
    if m := re.search(r"HTTP\s*(\d{3})", r):
        return f"HTTP {m.group(1)}"
    for key, label in (("無法確認 robots", "無法確認 robots.txt（保守停止）"), ("robots", "robots.txt 不允許"),
                       ("Timeout", "連線逾時"), ("SSL", "SSL 憑證錯誤"),
                       ("ConnectionError", "連線失敗"), ("Content-Type", "非 HTML 內容"),
                       ("private", "私人或下架影片"), ("unavailable", "影片無法播放"), ("登入", "需要登入")):
        if key.lower() in r.lower():
            return label
    return r[:24]


def compute(records: list[dict], claims: list[dict]) -> dict:
    teacher = [r for r in records if r.get("origin") == "teacher"]
    content = [r for r in records if r.get("source_role") != "discovery"]

    def rate(rows, key, value):
        return round(sum(r[key] == value for r in rows) / len(rows), 3) if rows else 0.0

    by_origin = {}
    for r in records:
        by_origin.setdefault(r.get("origin", ""), Counter())[r["processing_status"]] += 1

    domains = Counter()
    for r in content:
        host = (urlsplit(r["source_url"]).hostname or "").removeprefix("www.")
        domains["YouTube" if "youtu" in host else host] += 1

    reasons = Counter(short_reason(r.get("crawl_reason", "")) for r in records
                      if r["crawl_status"] in ("failed", "unavailable"))
    partial_reasons = Counter()
    for r in records:
        if r["processing_status"] == "partial":
            partial_reasons[{"missing": "尚無清理後正文／字幕", "low_quality": "內容品質不足",
                             "fallback": "暫用原始 HTML"}.get(r["content_status"], r["content_status"])] += 1

    keywords = Counter(k for r in records for k in r.get("keywords") or [])
    article_imgs = sum(1 for r in records for i in r["images"] if i.get("kind") != "video_frame")
    frames = sum(1 for r in records for i in r["images"] if i.get("kind") == "video_frame")
    subtitle_src = Counter((r.get("pipeline", {}).get("video", {}).get("subtitle_source") or "無字幕").split()[0]
                           for r in records if r["type"] == "video" and r["crawl_status"] == "success")
    return {
        "total": len(records),
        "teacher_total": len(teacher),
        "teacher_crawl_success_rate": rate(teacher, "crawl_status", "success"),
        "teacher_complete_rate": rate(teacher, "processing_status", "complete"),
        "by_type": dict(Counter(r["type"] for r in records)),
        "by_origin": {k: dict(v) for k, v in by_origin.items()},
        "processing_status": dict(Counter(r["processing_status"] for r in records)),
        "crawl_status": dict(Counter(r["crawl_status"] for r in records)),
        "content_chars": sum(len(compact(r["content"])) for r in records),
        "article_images": article_imgs,
        "video_frames": frames,
        "subtitle_segments": sum(len(r["timestamps"]) for r in records if r["type"] == "video"),
        "subtitle_source": dict(subtitle_src),
        "top_domains": domains.most_common(12),
        "failure_reasons": reasons.most_common(),
        "partial_reasons": partial_reasons.most_common(),
        "topics": Counter(r["topics"]["primary"] for r in records if r.get("topics")).most_common(),
        "top_keywords": keywords.most_common(15),
        "verdicts": dict(Counter(c["verdict"] for c in claims)),
        "claims": len(claims),
    }


# ---------------------------------------------------------------- 圖表
def setup_matplotlib():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    wanted = ["Microsoft JhengHei", "PingFang TC", "Noto Sans CJK TC", "Noto Sans TC",
              "Heiti TC", "Noto Sans CJK JP", "WenQuanYi Zen Hei", "Arial Unicode MS"]
    have = {f.name for f in font_manager.fontManager.ttflist}
    fonts = [f for f in wanted if f in have] or ["DejaVu Sans"]
    plt.rcParams.update({
        "font.sans-serif": fonts + ["DejaVu Sans"], "font.family": "sans-serif",
        "axes.unicode_minus": False, "figure.facecolor": SURFACE, "axes.facecolor": SURFACE,
        "axes.edgecolor": GRID, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK,
        "font.size": 11, "axes.titlesize": 14, "axes.titleweight": "bold", "axes.titlecolor": INK,
        "axes.titlelocation": "left", "axes.titlepad": 14,
    })
    return plt


def _clean_axes(ax, xgrid=True):
    from matplotlib.ticker import MaxNLocator
    ax.xaxis.set_major_locator(MaxNLocator(integer=True))  # 筆數只會是整數
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(axis="y", length=0)
    if xgrid:
        ax.xaxis.grid(True, color=GRID, linewidth=0.8)
        ax.set_axisbelow(True)


def hbar(plt, items: list[tuple[str, int]], title: str, path: Path, unit: str = "筆") -> bool:
    if not items:
        return False
    labels = [str(k) for k, _ in items][::-1]
    values = [v for _, v in items][::-1]
    fig, ax = plt.subplots(figsize=(8, 0.42 * len(items) + 1.3))
    bars = ax.barh(labels, values, color=SERIES, height=0.62, edgecolor=SURFACE, linewidth=2)
    vmax = max(values) or 1
    for b, v in zip(bars, values):
        ax.text(b.get_width() + vmax * 0.015, b.get_y() + b.get_height() / 2, f"{v}",
                va="center", ha="left", color=INK2, fontsize=10)
    ax.set_xlim(0, vmax * 1.12)
    ax.set_title(title)
    ax.set_xlabel(unit)
    _clean_axes(ax)
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return True


def status_chart(plt, stats: dict, path: Path) -> bool:
    groups = [o for o in ("teacher", "extra", "discovered", "") if o in stats["by_origin"]]
    if not groups:
        return False
    fig, ax = plt.subplots(figsize=(8.5, 0.7 * len(groups) + 1.9))
    left = [0] * len(groups)
    labels = [ORIGIN_LABEL[g] for g in groups][::-1]
    groups = groups[::-1]
    for st in STATUS_ORDER:
        vals = [stats["by_origin"][g].get(st, 0) for g in groups]
        if not any(vals):
            continue
        ax.barh(labels, vals, left=left, color=STATUS_COLORS[st], height=0.58,
                edgecolor=SURFACE, linewidth=2, label=PROCESSING_STATUS[st])
        for i, v in enumerate(vals):
            if v >= 2:
                ax.text(left[i] + v / 2, i, str(v), ha="center", va="center", fontsize=10,
                        color=INK if st in ("partial", "pending", "unavailable") else "white")
        left = [l + v for l, v in zip(left, vals)]
    for i, total in enumerate(left):
        ax.text(total + max(left) * 0.015, i, f"共 {total}", va="center", color=INK2, fontsize=10)
    ax.set_xlim(0, max(left) * 1.13)
    ax.set_title("各來源的整體處理狀態")
    ax.set_xlabel("筆")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.32 if len(groups) < 3 else -0.22),
              ncol=5, frameon=False, fontsize=10, handlelength=1.2)
    _clean_axes(ax)
    fig.tight_layout()
    fig.savefig(path, dpi=160, bbox_inches="tight")
    plt.close(fig)
    return True


# ---------------------------------------------------------------- 輸出
def write_csv(path: Path, header: list[str], rows: list) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def table(header: list[str], rows: list) -> list[str]:
    out = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return out + [""]


def report(root=".", output_dir="output", report_dir="report", charts=True) -> dict:
    root = Path(root).resolve()
    out, rep = root / output_dir, root / report_dir
    records, _ = load_index(out / "index.jsonl")
    if not records:
        print("沒有 output/index.jsonl，請先執行 python -m crawler.knowledge_builder")
        return {}
    claims = load_claims(rep / "source_verification.csv")
    stats = compute(records, claims)
    sdir = out / "statistics"
    sdir.mkdir(parents=True, exist_ok=True)
    (sdir / "summary.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    write_csv(sdir / "status_by_origin.csv", ["origin"] + STATUS_ORDER,
              [[o] + [c.get(s, 0) for s in STATUS_ORDER] for o, c in stats["by_origin"].items()])
    write_csv(sdir / "topics.csv", ["topic", "count"], stats["topics"])
    write_csv(sdir / "top_domains.csv", ["domain", "count"], stats["top_domains"])
    write_csv(sdir / "failure_reasons.csv", ["reason", "count"], stats["failure_reasons"])
    write_csv(sdir / "top_keywords.csv", ["keyword", "documents"], stats["top_keywords"])

    made = {}
    if charts:
        try:
            plt = setup_matplotlib()
            made["status"] = status_chart(plt, stats, sdir / "status_by_origin.png")
            made["topics"] = hbar(plt, stats["topics"], "主題分類（主分類）", sdir / "topics.png", "篇")
            made["domains"] = hbar(plt, stats["top_domains"], "資料來源網站（前 12 名）", sdir / "top_domains.png")
            made["failures"] = hbar(plt, stats["failure_reasons"], "失敗與無法存取的原因", sdir / "failure_reasons.png")
            shared = [(k, v) for k, v in stats["top_keywords"] if v >= 2]  # 只出現 1 篇的不畫
            made["keywords"] = hbar(plt, shared, "常見關鍵字（出現在 2 篇以上）", sdir / "top_keywords.png", "篇")
        except ImportError:
            print("未安裝 matplotlib，略過圖表（pip install matplotlib）")

    S = stats
    L = ["# 成果統計", "", "> 由 `python -m crawler.statistics_report` 依 output/index.jsonl 自動產生。"
         "整體狀態分為：完整完成（取得＋可用內容）、部分完成（取得但內容不足）、無法存取、失敗、未處理。", "",
         "## 重點數字", "",
         *table(["項目", "數值"], [
             ["知識庫總筆數", S["total"]],
             ["老師指定網址", S["teacher_total"]],
             ["老師網址：取得成功率", f"{S['teacher_crawl_success_rate']:.0%}"],
             ["老師網址：完整完成率（取得＋可用內容）", f"{S['teacher_complete_rate']:.0%}"],
             ["網頁／影片", f"{S['by_type'].get('web', 0)}／{S['by_type'].get('video', 0)}"],
             ["文章圖片／影片代表畫面", f"{S['article_images']}／{S['video_frames']}"],
             ["影片字幕段數", f"{S['subtitle_segments']:,}"],
             ["內容文字總量（字）", f"{S['content_chars']:,}"],
             ["來源查證筆數", S["claims"]],
         ]),
         "## 各來源的處理狀態", ""]
    if made.get("status"):
        L += [f"![各來源的整體處理狀態](../{output_dir}/statistics/status_by_origin.png)", ""]
    L += table(["來源"] + [PROCESSING_STATUS[s] for s in STATUS_ORDER] + ["合計"],
               [[ORIGIN_LABEL.get(o, o)] + [c.get(s, 0) for s in STATUS_ORDER] + [sum(c.values())]
                for o, c in S["by_origin"].items()])
    L += ["取得階段（crawl_status）：" + "、".join(f"{CRAWL_STATUS[k]} {v}" for k, v in S["crawl_status"].items()), ""]
    if S["partial_reasons"]:
        L += ["部分完成的原因：" + "、".join(f"{k} {v}" for k, v in S["partial_reasons"]), ""]
    sections = [("failures", "常見失敗原因", "failure_reasons", ["原因", "筆數"], S["failure_reasons"]),
                ("topics", "主題分類", "topics", ["主題", "篇數"], S["topics"]),
                ("domains", "資料來源網站", "top_domains", ["網站", "筆數"], S["top_domains"]),
                ("keywords", "常見關鍵字", "top_keywords", ["關鍵字", "篇數"], S["top_keywords"])]
    for key, title, fname, header, rows in sections:
        L += [f"## {title}", ""]
        if not rows:
            L += ["（目前沒有資料）", ""]
            continue
        if made.get(key):
            L += [f"![{title}](../{output_dir}/statistics/{fname}.png)", ""]
        L += table(header, rows)
    if S["subtitle_source"]:
        L += ["## 影片字幕來源", ""] + table(["來源", "影片數"], list(S["subtitle_source"].items()))
    if S["verdicts"]:
        L += ["## 來源查證結果", ""] + table(["判定", "筆數"], list(S["verdicts"].items()))
        L += ["詳細內容見 [source_verification.md](source_verification.md)。", ""]
    rep.mkdir(parents=True, exist_ok=True)
    (rep / "statistics.md").write_text("\n".join(L), encoding="utf-8")
    print(f"統計完成：{S['total']} 筆；老師網址取得成功率 {S['teacher_crawl_success_rate']:.0%}、"
          f"完整完成率 {S['teacher_complete_rate']:.0%}")
    print(f"輸出：{sdir}（{sum(bool(v) for v in made.values())} 張圖）、{rep / 'statistics.md'}")
    return stats


def main(argv=None):
    p = argparse.ArgumentParser(description="組員 4：成果統計與圖表")
    p.add_argument("--root", default=".")
    p.add_argument("--output-dir", default="output")
    p.add_argument("--report-dir", default="report")
    p.add_argument("--no-charts", action="store_true")
    a = p.parse_args(argv)
    report(a.root, a.output_dir, a.report_dir, charts=not a.no_charts)


if __name__ == "__main__":
    main()
