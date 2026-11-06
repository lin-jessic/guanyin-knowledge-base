"""組員 4：知識庫搜尋（展示用）。

  python -m crawler.kb_search 白沙岬燈塔
  python -m crawler.kb_search 甘泉寺 --type video        # 只搜影片，會列出字幕時間點
  python -m crawler.kb_search 藻礁 --topic 生態保育 --limit 5

顯示：標題、原始來源、相關段落、相關圖片；影片顯示命中字幕的時間點與 YouTube 跳轉連結。
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

from .kb_schema import seconds_to_hms, youtube_id
from .validator import load_index


def snippets(text: str, q: str, width: int = 40, limit: int = 3) -> list[str]:
    flat = re.sub(r"\s+", " ", text)
    out = []
    for m in re.finditer(re.escape(q), flat):
        s, e = max(0, m.start() - width), min(len(flat), m.end() + width)
        out.append(("…" if s else "") + flat[s:e].replace(q, f"【{q}】") + ("…" if e < len(flat) else ""))
        if len(out) >= limit:
            break
    return out


def search(records: list[dict], query: str, type_=None, topic=None) -> list[tuple[float, dict, dict]]:
    terms = [t for t in query.split() if t]
    results = []
    for r in records:
        if type_ and r["type"] != type_:
            continue
        if topic and topic not in [r.get("topics", {}).get("primary")] + r.get("topics", {}).get("secondary", []):
            continue
        title, content = r.get("title", ""), r.get("content", "")
        if not all(t in title or t in content or t in r.get("keywords", []) for t in terms):
            continue
        score = sum(title.count(t) * 5 + content.count(t) + (3 if t in r.get("keywords", []) else 0) for t in terms)
        hits = {"snippets": [s for t in terms for s in snippets(content, t)][:3], "segments": [], "images": []}
        if r["type"] == "video":
            hits["segments"] = [s for s in r.get("timestamps") or [] if any(t in s.get("text", "") for t in terms)][:5]
        hits["images"] = [i for i in r.get("images") or []
                          if any(t in (i.get("caption") or "") or t in (i.get("context_text") or "") for t in terms)][:3]
        if r.get("content_status") != "ok":
            score *= 0.5  # 品質不足或待審核的內容排後面
        results.append((score, r, hits))
    results.sort(key=lambda x: -x[0])
    return results


def main(argv=None):
    p = argparse.ArgumentParser(description="搜尋觀音知識庫")
    p.add_argument("query", help="關鍵字，可用空白分隔多個（全部都要出現）")
    p.add_argument("--type", choices=["web", "video"])
    p.add_argument("--topic", help="主題，例如 歷史文化")
    p.add_argument("--limit", type=int, default=8)
    p.add_argument("--index", default="output/index.jsonl")
    a = p.parse_args(argv)
    records, _ = load_index(Path(a.index))
    if not records:
        print("知識庫是空的，請先執行 python -m crawler.knowledge_builder")
        return
    res = search(records, a.query, a.type, a.topic)
    print(f"「{a.query}」共 {len(res)} 筆結果\n")
    for score, r, hits in res[: a.limit]:
        kind = "影片" if r["type"] == "video" else "網頁"
        print(f"■ [{r['id']}] {r['title']}（{kind}｜{r.get('source_name', '')}）")
        print(f"  來源：{r['source_url']}")
        meta = []
        if r.get("topics", {}).get("primary"):
            meta.append(f"主題：{r['topics']['primary']}")
        if r.get("keywords"):
            meta.append("關鍵字：" + "、".join(r["keywords"]))
        meta.append(f"狀態：{r.get('processing_status')}")
        print("  " + "｜".join(meta))
        for s in hits["snippets"]:
            print(f"  ・{s}")
        vid = youtube_id(r["source_url"])
        for seg in hits["segments"]:
            t = seg.get("start_seconds", 0)
            print(f"  ▶ {seconds_to_hms(t)}  {seg.get('text', '')}  https://youtu.be/{vid}?t={int(float(t))}")
        for img in hits["images"]:
            print(f"  🖼 output/{img.get('file')}  {img.get('caption', '')}  （來源 {img.get('source_url', '')}）")
        for f in [f for f in r.get("quality_flags", []) if "字幕" in f][:1]:
            print(f"  ⚠ {f}")
        print()


if __name__ == "__main__":
    main()
