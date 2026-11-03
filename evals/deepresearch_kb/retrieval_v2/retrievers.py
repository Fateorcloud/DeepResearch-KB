"""Candidate retrievers compared by the benchmark.

Every candidate reads the same active chunks the product stores (so the
version filter is identical); only tokenisation and ranking differ. Vector,
hybrid and rerank need the optional ``fastembed`` package and ``jieba`` needs
``jieba``; neither is a project dependency.
"""

import hashlib
import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np

EMBED_MODEL = "BAAI/bge-small-zh-v1.5"
RERANK_MODEL = "BAAI/bge-reranker-base"
# Recommended query instruction for the bge zh v1.5 models.
QUERY_PREFIX = "为这个句子生成表示以用于检索相关文章："
RRF_K = 60
RERANK_POOL = 20
# Smaller windows for the chunking comparison; bge-small-zh truncates at 512 tokens,
# which the product's 1000-character chunks reach.
SMALL_CHUNK, SMALL_OVERLAP = 400, 80
_RUNS = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]+")
_CJK = re.compile(r"[\u4e00-\u9fff]")
MODEL_CACHE = Path.home() / ".cache" / "fastembed"


@dataclass(frozen=True)
class Hit:
    chunk_id: str
    logical_path: str
    version: int
    text: str
    score: float = 0.0


def resplit(chunks, size, overlap):
    """Rejoin each document's contiguous chunks and cut overlapping windows."""
    documents = {}
    for chunk in chunks:
        documents.setdefault((chunk.logical_path, chunk.version), []).append(chunk.text)
    windows = []
    for (path, version), parts in documents.items():
        text = "".join(parts)
        starts = range(0, max(len(text) - overlap, 1), size - overlap)
        windows.extend(Hit(f"{path}@{version}#{i}", path, version, text[start:start + size])
                       for i, start in enumerate(starts))
    return windows


def bigrams(text):
    """CJK runs become overlapping character bigrams; Latin words stay whole."""
    for run in _RUNS.findall(text.lower()):
        if not _CJK.match(run):
            yield run
        elif len(run) == 1:
            yield run
        else:
            yield from (run[i:i + 2] for i in range(len(run) - 1))


def trigrams(text):
    """Query terms for SQLite's trigram tokenizer, which cannot match < 3 chars."""
    for run in _RUNS.findall(text.lower()):
        yield from (run[i:i + 3] for i in range(len(run) - 2))


def jieba_words(text):
    import jieba
    return [w for w in (t.strip().lower() for t in jieba.cut_for_search(text)) if _RUNS.fullmatch(w)]


def _match(terms):
    terms = list(dict.fromkeys(terms))
    return " OR ".join('"' + t.replace('"', '""') + '"' for t in terms)


class LexicalIndex:
    """In-memory FTS5 index over pre-analysed chunk text, ranked by bm25."""

    def __init__(self, chunks, *, index_text, query_terms, tokenize="unicode61"):
        self.chunks, self.query_terms = chunks, query_terms
        self.db = sqlite3.connect(":memory:")
        self.db.execute(f"CREATE VIRTUAL TABLE t USING fts5(body, tokenize='{tokenize}')")
        self.db.executemany("INSERT INTO t(rowid, body) VALUES (?, ?)",
                            [(i, index_text(c.text)) for i, c in enumerate(chunks)])

    def search(self, query, limit):
        match = _match(self.query_terms(query))
        if not match:
            return []
        rows = self.db.execute("SELECT rowid, bm25(t) FROM t WHERE t MATCH ? ORDER BY bm25(t), rowid LIMIT ?",
                               (match, limit)).fetchall()
        return [replace(self.chunks[i], score=-s) for i, s in rows]


class VectorIndex:
    """Dense retrieval with cosine similarity; embeddings cached per corpus."""

    def __init__(self, chunks, cache_dir, model=EMBED_MODEL):
        from fastembed import TextEmbedding
        self.chunks = chunks
        self.model = TextEmbedding(model, cache_dir=str(MODEL_CACHE))
        digest = hashlib.sha256(model.encode())
        for chunk in chunks:
            digest.update(chunk.chunk_id.encode() + b"\0" + chunk.text.encode() + b"\0")
        path = Path(cache_dir) / f"embeddings-{digest.hexdigest()[:16]}.npy"
        if path.is_file():
            matrix = np.load(path)
        else:
            matrix = np.array(list(self.model.passage_embed([c.text for c in chunks])), dtype=np.float32)
            path.parent.mkdir(parents=True, exist_ok=True)
            np.save(path, matrix)
        self.matrix = matrix / np.linalg.norm(matrix, axis=1, keepdims=True)

    def search(self, query, limit):
        vector = np.array(next(iter(self.model.query_embed([QUERY_PREFIX + query]))), dtype=np.float32)
        scores = self.matrix @ (vector / np.linalg.norm(vector))
        order = np.argsort(-scores, kind="stable")[:limit]
        return [replace(self.chunks[i], score=float(scores[i])) for i in order]


def rrf(rankings, limit, k=RRF_K):
    """Reciprocal rank fusion of several ranked hit lists."""
    scores, hits = {}, {}
    for ranking in rankings:
        for rank, hit in enumerate(ranking, 1):
            scores[hit.chunk_id] = scores.get(hit.chunk_id, 0.0) + 1 / (k + rank)
            hits.setdefault(hit.chunk_id, hit)
    order = sorted(scores, key=lambda cid: (-scores[cid], cid))[:limit]
    return [replace(hits[cid], score=scores[cid]) for cid in order]


class Workbench:
    """Builds each index lazily once per evaluation run."""

    def __init__(self, store, kb, cache_dir):
        self.store, self.kb, self.cache_dir = store, kb, cache_dir
        self._chunks, self._built = None, {}

    @property
    def chunks(self):
        if self._chunks is None:
            with closing(self.store._connect()) as db:
                rows = db.execute("""
                    SELECT c.id, d.logical_path, c.version, c.text FROM chunk c
                    JOIN document d ON d.id = c.document_id
                    JOIN document_version v ON v.document_id = c.document_id AND v.version = c.version
                    WHERE d.knowledge_base_id = ? AND v.status = 'active'
                    ORDER BY d.logical_path, c.ordinal""", (self.kb,)).fetchall()
            self._chunks = [Hit(*row) for row in rows]
        return self._chunks

    @property
    def all_version_chunks(self):
        """Control set: every version's chunks, including superseded ones."""
        if "all-versions" not in self._built:
            with closing(self.store._connect()) as db:
                rows = db.execute("""
                    SELECT c.id, d.logical_path, c.version, c.text FROM chunk c
                    JOIN document d ON d.id = c.document_id
                    WHERE d.knowledge_base_id = ?
                    ORDER BY d.logical_path, c.version, c.ordinal""", (self.kb,)).fetchall()
            self._built["all-versions"] = [Hit(*row) for row in rows]
        return self._built["all-versions"]

    def bigram_all_versions(self):
        return self._once("bigram-all-versions", lambda: LexicalIndex(
            self.all_version_chunks, index_text=lambda t: " ".join(bigrams(t)), query_terms=bigrams))

    def chunk_set(self, small=False):
        if not small:
            return self.chunks
        return self._once("small-chunks", lambda: resplit(self.chunks, SMALL_CHUNK, SMALL_OVERLAP))

    def _once(self, name, build):
        if name not in self._built:
            self._built[name] = build()
        return self._built[name]

    def bigram(self, small=False):
        return self._once(("bigram", small), lambda: LexicalIndex(
            self.chunk_set(small), index_text=lambda t: " ".join(bigrams(t)), query_terms=bigrams))

    def trigram(self):
        return self._once("trigram", lambda: LexicalIndex(
            self.chunks, index_text=lambda t: t, query_terms=trigrams, tokenize="trigram"))

    def jieba(self):
        import logging
        import jieba
        jieba.setLogLevel(logging.WARNING)
        return self._once("jieba", lambda: LexicalIndex(
            self.chunks, index_text=lambda t: " ".join(jieba_words(t)), query_terms=jieba_words))

    def vector(self, small=False):
        return self._once(("vector", small), lambda: VectorIndex(self.chunk_set(small), self.cache_dir))

    def reranker(self):
        def build():
            from fastembed.rerank.cross_encoder import TextCrossEncoder
            return TextCrossEncoder(RERANK_MODEL, cache_dir=str(MODEL_CACHE))
        return self._once("reranker", build)

    def hybrid_search(self, query, limit, small=False):
        pool = max(limit, 50)
        return rrf([self.bigram(small).search(query, pool), self.vector(small).search(query, pool)], limit)

    def rerank_search(self, query, limit):
        pool = self.hybrid_search(query, RERANK_POOL)
        scores = list(self.reranker().rerank(query, [hit.text for hit in pool]))
        order = sorted(range(len(pool)), key=lambda i: (-scores[i], i))[:limit]
        return [replace(pool[i], score=float(scores[i])) for i in order]


RETRIEVERS = {
    "fts5": lambda bench: lambda q, k: bench.store.retrieve([bench.kb], q, limit=k),
    "trigram": lambda bench: bench.trigram().search,
    "bigram": lambda bench: bench.bigram().search,
    "bigram_all_versions": lambda bench: bench.bigram_all_versions().search,
    "jieba": lambda bench: bench.jieba().search,
    "vector": lambda bench: bench.vector().search,
    "hybrid": lambda bench: bench.hybrid_search,
    "rerank": lambda bench: bench.rerank_search,
    "bigram_c400": lambda bench: bench.bigram(small=True).search,
    "vector_c400": lambda bench: bench.vector(small=True).search,
    "hybrid_c400": lambda bench: lambda q, k: bench.hybrid_search(q, k, small=True),
}
