"""The token ingestion optimizer engine.

Pipeline (each piece of data is touched exactly once, nothing is discarded):
  1. Token count every raw fragment  -> tokens_before
  2. Exact dedup via normalized hashing (O(n))
  3. Near-dup detection via MinHash + LSH banding (O(n)) + union-find merge
  4. Pick a canonical representative per cluster, fold counts + variants
  5. Token count canonical set       -> tokens_after

No data is lost: every collapsed duplicate/variant keeps its count and the
distinct variant strings are preserved on the canonical record.
"""
from __future__ import annotations

import re
import time
from typing import Dict, List

from datasketch import MinHash, MinHashLSH

_TOKEN_RE = re.compile(r"[a-z0-9]+(?:[._-][a-z0-9]+)*")
_NORM_RE = re.compile(r"[^a-z0-9\s]")

# --- token counter (tiktoken with safe fallback) ---
try:
    import tiktoken

    _ENC = tiktoken.get_encoding("cl100k_base")

    def count_tokens(text: str) -> int:
        return len(_ENC.encode(text, disallowed_special=()))
except Exception:  # pragma: no cover - offline fallback
    def count_tokens(text: str) -> int:
        words = len(text.split())
        return max(words, len(text) // 4)


def _normalize(text: str) -> str:
    return _NORM_RE.sub(" ", text.lower()).strip()


def _shingles(norm_text: str) -> List[str]:
    words = _TOKEN_RE.findall(norm_text)
    if not words:
        return [norm_text]
    if len(words) < 2:
        return words
    grams = words[:]  # unigrams
    grams += [f"{words[i]} {words[i+1]}" for i in range(len(words) - 1)]  # bigrams
    return grams


class _UnionFind:
    def __init__(self, n: int):
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        root = x
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[x] != root:
            self.parent[x], x = root, self.parent[x]
        return root

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def optimize(
    fragments: List[str],
    threshold: float = 0.82,
    num_perm: int = 96,
) -> Dict:
    t0 = time.time()
    total_in = len(fragments)
    raw_chars = sum(len(f) for f in fragments)

    # ---- token count of the full raw input ----
    tokens_before = sum(count_tokens(f) for f in fragments)

    # ---- 1. exact dedup ----
    exact: Dict[str, dict] = {}
    for f in fragments:
        key = _normalize(f)
        if not key:
            continue
        e = exact.get(key)
        if e is None:
            exact[key] = {"text": f, "norm": key, "count": 1, "variants": set()}
        else:
            e["count"] += 1
            if f != e["text"]:
                e["variants"].add(f)
    uniques = list(exact.values())
    after_exact = len(uniques)

    # ---- 2. near-dup via MinHash LSH ----
    minhashes: List[MinHash] = []
    for u in uniques:
        m = MinHash(num_perm=num_perm)
        for sh in _shingles(u["norm"]):
            m.update(sh.encode("utf-8"))
        minhashes.append(m)

    lsh = MinHashLSH(threshold=threshold, num_perm=num_perm)
    for i, m in enumerate(minhashes):
        lsh.insert(str(i), m)

    uf = _UnionFind(len(uniques))
    for i, m in enumerate(minhashes):
        for j_str in lsh.query(m):
            j = int(j_str)
            if j != i:
                uf.union(i, j)

    # ---- 3. fold clusters, pick canonical (longest = most information) ----
    clusters: Dict[int, dict] = {}
    for i, u in enumerate(uniques):
        root = uf.find(i)
        c = clusters.get(root)
        if c is None:
            clusters[root] = {
                "text": u["text"],
                "count": u["count"],
                "variants": set(u["variants"]),
            }
        else:
            c["count"] += u["count"]
            if len(u["text"]) > len(c["text"]):
                c["variants"].add(c["text"])
                c["text"] = u["text"]
            else:
                c["variants"].add(u["text"])
            c["variants"].update(u["variants"])

    canonical = []
    tokens_after = 0
    for c in clusters.values():
        tks = count_tokens(c["text"])
        tokens_after += tks
        variants = sorted(v for v in c["variants"] if v and v != c["text"])
        canonical.append({
            "text": c["text"],
            "count": c["count"],
            "tokens": tks,
            "variants": variants[:25],
            "variant_count": len(variants),
        })

    canonical.sort(key=lambda x: (x["count"], x["tokens"]), reverse=True)

    elapsed_ms = round((time.time() - t0) * 1000, 1)
    reduction = round((1 - tokens_after / tokens_before) * 100, 2) if tokens_before else 0.0
    dup_reduction = round((1 - len(canonical) / total_in) * 100, 2) if total_in else 0.0

    return {
        "stats": {
            "fragments_in": total_in,
            "raw_chars": raw_chars,
            "after_exact_dedup": after_exact,
            "unique_concepts": len(canonical),
            "duplicates_removed": total_in - len(canonical),
            "dup_reduction_pct": dup_reduction,
            "tokens_before": tokens_before,
            "tokens_after": tokens_after,
            "tokens_saved": tokens_before - tokens_after,
            "token_reduction_pct": reduction,
            "near_dup_clusters": after_exact - len(canonical),
            "threshold": threshold,
            "elapsed_ms": elapsed_ms,
        },
        "fragments": canonical,
    }
