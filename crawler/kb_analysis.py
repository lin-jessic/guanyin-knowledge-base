"""組員 4：文字分析——重複偵測、主題分類、關鍵字、字幕雜訊檢查。

全部用 Python 標準函式庫＋jieba 完成（沒有 jieba 也能跑，會改用字元切分），
規則與詞典放在 data/kb/，新增主題或地名不用改程式。
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import warnings
from collections import Counter, defaultdict
from pathlib import Path

from .kb_schema import compact

KB_DIR = Path(__file__).resolve().parent.parent / "data" / "kb"
CJK = re.compile(r"[一-鿿]")


# ---------------------------------------------------------------- 設定檔
def load_word_list(path: Path) -> list[str]:
    if not path.is_file():
        return []
    words = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.split("#", 1)[0].strip()
        words.extend(w for w in line.split() if w)
    return words


def load_rules(path: Path | None = None) -> dict:
    path = path or KB_DIR / "topic_rules.json"
    return json.loads(path.read_text(encoding="utf-8-sig"))


class TextTools:
    """斷詞器＋詞典。建一次，重複使用。"""

    def __init__(self, kb_dir: Path = KB_DIR):
        self.local_terms = load_word_list(kb_dir / "local_terms.txt")
        self.stopwords = set(load_word_list(kb_dir / "stopwords.txt"))
        self.rules = load_rules(kb_dir / "topic_rules.json")
        self._jieba = None
        try:
            warnings.filterwarnings("ignore", category=SyntaxWarning)
            import jieba
            jieba.setLogLevel(logging.WARNING)
            for t in self.local_terms:
                jieba.add_word(t, freq=200000)
            for topic in self.rules.get("topics", []):
                for t in topic["keywords"]:
                    jieba.add_word(t, freq=20000)
            self._jieba = jieba
        except ImportError:
            pass
        self.method = "jieba 斷詞" if self._jieba else "字元切分（未安裝 jieba）"

    def tokens(self, text: str, nouns_only: bool = False) -> list[str]:
        """nouns_only=True：只留名詞類（關鍵字用），口語字幕裡的「大哥」「揮手」就不會入選。"""
        if self._jieba and nouns_only:
            import jieba.posseg as pseg
            keep = set(self.local_terms) | {t for tp in self.rules.get("topics", []) for t in tp["keywords"]}
            words = [w for w, flag in pseg.cut(text)
                     if w in keep or flag in ("n", "ns", "nt", "nz", "nl", "ng", "vn")]
        elif self._jieba:
            words = self._jieba.cut(text)
        else:  # 後備：在地詞＋中文二字詞
            words = [t for t in self.local_terms if t in text]
            for seg in re.findall(r"[一-鿿]+", text):
                words.extend(seg[i:i + 2] for i in range(len(seg) - 1))
        out = []
        for w in words:
            w = w.strip()
            if len(w) < 2 or w in self.stopwords or not CJK.search(w):
                continue
            out.append(w)
        return out


# ---------------------------------------------------------------- 關鍵字
def extract_keywords(docs: dict[str, dict], tools: TextTools, k_min=3, k_max=5) -> dict[str, list[str]]:
    """TF-IDF：在這篇常出現、在其他篇少出現的詞分數高。觀音在地詞、標題中的詞再加權。
    關鍵字一定是正文裡真的出現過的詞（validator 會再檢查一次）。"""
    toks = {rid: tools.tokens(d["title"] + "\n" + d["content"], nouns_only=True) for rid, d in docs.items()}
    df = Counter()
    for words in toks.values():
        df.update(set(words))
    n = max(len(docs), 1)
    local = set(tools.local_terms)
    result = {}
    for rid, words in toks.items():
        tf = Counter(words)
        if not tf:
            result[rid] = []
            continue
        title = docs[rid]["title"]
        content = docs[rid]["content"]
        scored = []
        for w, c in tf.items():
            if w not in content:
                continue
            idf = math.log((1 + n) / (1 + df[w])) + 1
            s = (1 + math.log(c)) * idf
            if w in local:
                s *= 1.6
            if w in title:
                s *= 1.4
            scored.append((s, w))
        scored.sort(key=lambda x: (-x[0], x[1]))
        picked: list[str] = []
        for _, w in scored:
            if any(w in p or p in w for p in picked):  # 避免「白沙岬」「白沙岬燈塔」同時入選
                continue
            picked.append(w)
            if len(picked) == k_max:
                break
        if len(picked) < k_min:  # 文章太短：補正文中出現的在地詞
            picked += [t for t in tools.local_terms if t in content and t not in picked][: k_min - len(picked)]
        result[rid] = picked
    return result


# ---------------------------------------------------------------- 主題分類
def classify(title: str, content: str, rules: dict) -> dict:
    text = title * int(rules.get("title_weight", 3)) + "\n" + content
    scores, evidence = {}, {}
    for topic in rules.get("topics", []):
        hits = Counter({w: text.count(w) for w in topic["keywords"] if w in text})
        if not hits:
            continue
        # 命中「幾種」詞比「幾次」重要：每個詞最多算 5 次，再加種類數 ×2
        scores[topic["name"]] = sum(min(c, 5) for c in hits.values()) + 2 * len(hits)
        evidence[topic["name"]] = [w for w, _ in hits.most_common(5)]
    ranked = sorted(scores.items(), key=lambda x: -x[1])
    if not ranked or ranked[0][1] < rules.get("min_score", 3):
        return {"primary": "其他", "secondary": [], "scores": dict(ranked), "evidence": evidence,
                "method": "規則計分（data/kb/topic_rules.json）"}
    top = ranked[0][1]
    ratio = rules.get("secondary_ratio", 0.5)
    return {
        "primary": ranked[0][0],
        "secondary": [t for t, s in ranked[1:3] if s >= top * ratio],
        "scores": dict(ranked),
        "evidence": {t: evidence[t] for t, _ in ranked[:3]},
        "method": "規則計分（data/kb/topic_rules.json）",
    }


# ---------------------------------------------------------------- 重複／相似
def shingles(text: str, n: int = 3) -> Counter:
    s = compact(re.sub(r"[^\w一-鿿]", "", text))
    return Counter(s[i:i + n] for i in range(max(len(s) - n + 1, 0)))


def cosine(a: Counter, b: Counter) -> float:
    if not a or not b:
        return 0.0
    if len(a) > len(b):
        a, b = b, a
    dot = sum(v * b.get(k, 0) for k, v in a.items())
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0


def find_duplicates(docs: dict[str, dict], high=0.75, partial=0.4, min_chars=50) -> list[dict]:
    """完全重複：去空白後內容雜湊相同。高度相似：字元 3-gram 餘弦相似度。
    以倒排索引先找「有共同片段」的候選，資料變多時不必每兩篇都比。
    不刪除任何資料，只標記，保留每個來源的可追溯性。"""
    ids = [rid for rid, d in docs.items() if len(compact(d["content"])) >= min_chars]
    pairs: list[dict] = []
    by_hash = defaultdict(list)
    for rid in ids:
        by_hash[hashlib.sha256(compact(docs[rid]["content"]).encode()).hexdigest()].append(rid)
    exact = set()
    for group in by_hash.values():
        for other in group[1:]:
            pairs.append({"a": group[0], "b": other, "cosine": 1.0, "title_similarity": 1.0,
                          "level": "完全重複"})
            exact.add(tuple(sorted((group[0], other))))

    vecs = {rid: shingles(docs[rid]["content"]) for rid in ids}
    index = defaultdict(set)
    for rid, v in vecs.items():
        for g in v:
            index[g].add(rid)
    common = Counter()
    limit = max(10, len(ids) // 3)  # 太常見的片段（如「觀音區」）不拿來找候選
    for g, members in index.items():
        if 1 < len(members) <= limit:
            ms = sorted(members)
            for i in range(len(ms)):
                for j in range(i + 1, len(ms)):
                    common[(ms[i], ms[j])] += 1
    for (a, b), shared in common.items():
        if (a, b) in exact or shared < 5:
            continue
        sim = cosine(vecs[a], vecs[b])
        if sim < partial:
            continue
        tsim = cosine(shingles(docs[a]["title"], 2), shingles(docs[b]["title"], 2))
        pairs.append({"a": a, "b": b, "cosine": round(sim, 3), "title_similarity": round(tsim, 3),
                      "level": "幾乎相同（轉載）" if sim >= 0.95 else
                               "高度相似（可能轉載或改寫）" if sim >= high else "部分相似"})
    pairs.sort(key=lambda p: -p["cosine"])
    return pairs


# ---------------------------------------------------------------- 字幕雜訊
def clean_for_analysis(text: str) -> str:
    """分析前的清理（不改動原始 content）：拿掉 [music] 標記、重複超過 3 次的句子。"""
    lines = [re.sub(r"\[(music|音樂|掌聲|applause)\]", "", l, flags=re.I).strip() for l in text.splitlines()]
    lines = [l for l in lines if l]
    counts = Counter(lines)
    return "\n".join(l for l in lines if counts[l] <= 3)


def transcript_noise(text: str) -> tuple[list[str], bool]:
    """語音辨識常見問題：同一句一直重複、大量 [music]、幾乎沒有中文。
    回傳 (提醒清單, 是否嚴重)；嚴重的字幕不納入分類、關鍵字與相似度。"""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if len(lines) < 5:
        return [], False
    flags, severe = [], False
    top_line, top_count = Counter(lines).most_common(1)[0]
    repeat = top_count / len(lines)
    if repeat >= 0.15 and top_count >= 5:
        flags.append(f"字幕疑似辨識錯誤：「{top_line[:12]}」重複 {top_count} 次（{repeat:.0%}）")
        severe = repeat >= 0.25
    music = sum(bool(re.search(r"\[(music|音樂)\]", l, re.I)) for l in lines) / len(lines)
    if music >= 0.3:
        flags.append(f"字幕 {music:.0%} 為音樂標記")
        severe = severe or music >= 0.5
    cjk = sum(bool(CJK.search(l)) for l in lines) / len(lines)
    if cjk < 0.3:
        flags.append(f"字幕只有 {cjk:.0%} 含中文")
        severe = True
    return flags, severe
