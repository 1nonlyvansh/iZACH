"""
modules/rag_memory.py
Persistent vector memory for iZACH — stores every conversation in ChromaDB.
Semantic retrieval injects relevant past context into AI prompts.
"""

import os
import sys
import time
import threading

_DB_PATH = "izach_rag_db"
_COLLECTION_NAME = "izach_conversations"
_DISTANCE_THRESHOLD = 0.8  # cosine distance; below this = relevant
_MAX_RESULTS = 4

_collection = None
_init_lock  = threading.Lock()   # only ONE thread initialises ChromaDB at a time
_init_done  = False              # True once init succeeded or permanently failed
_init_ok    = False              # True only on success


def _get_collection():
    global _collection, _init_done, _init_ok

    # Fast path — already initialised
    if _init_done:
        return _collection

    with _init_lock:
        # Re-check inside lock (another thread may have finished while we waited)
        if _init_done:
            return _collection

        try:
            import chromadb
        except ImportError:
            print("[RAG] chromadb not installed. Run: pip install chromadb")
            _init_done = True
            return None

        try:
            from chromadb.utils import embedding_functions

            # ── Suppress tqdm download progress bars ──────────────────
            # ChromaDB prints the 80 MB ONNX model download to stdout/stderr.
            # We redirect both streams temporarily so the console stays clean.
            class _NullWriter:
                def write(self, *a): pass
                def flush(self):     pass

            _old_stdout, _old_stderr = sys.stdout, sys.stderr
            # Also set env var that tqdm checks
            _old_tqdm = os.environ.get("TQDM_DISABLE")
            os.environ["TQDM_DISABLE"] = "1"

            sys.stdout = _NullWriter()
            sys.stderr = _NullWriter()
            try:
                ef = embedding_functions.DefaultEmbeddingFunction()
                # Trigger model download NOW (inside the suppression block)
                ef(["warmup"])
            finally:
                sys.stdout = _old_stdout
                sys.stderr = _old_stderr
                if _old_tqdm is None:
                    os.environ.pop("TQDM_DISABLE", None)
                else:
                    os.environ["TQDM_DISABLE"] = _old_tqdm
            # ─────────────────────────────────────────────────────────

            client      = chromadb.PersistentClient(path=_DB_PATH)
            _collection = client.get_or_create_collection(
                name=_COLLECTION_NAME,
                embedding_function=ef,
                metadata={"hnsw:space": "cosine"},
            )
            _init_ok   = True
            print(f"[RAG] ChromaDB ready. {_collection.count()} conversations stored.")

        except Exception as e:
            print(f"[RAG] Init failed: {e}")
            _collection = None

        _init_done = True
        return _collection


def warmup():
    """Call once at startup (from main.py) before background services spin up.
    Blocks until ChromaDB + ONNX model are ready so threads don't race."""
    _get_collection()


def add_conversation(query: str, response: str) -> None:
    col = _get_collection()
    if col is None:
        return
    try:
        doc_id   = f"conv_{int(time.time() * 1000)}"
        combined = f"User: {query}\nAssistant: {response}"
        col.add(
            documents=[combined],
            metadatas=[{
                "query":    query,
                "response": response[:1000],
                "ts":       int(time.time()),
            }],
            ids=[doc_id],
        )
    except Exception as e:
        print(f"[RAG] Store failed: {e}")


def get_relevant_context(query: str, n: int = _MAX_RESULTS) -> str:
    col = _get_collection()
    if col is None:
        return ""
    try:
        count = col.count()
        if count == 0:
            return ""
        results = col.query(
            query_texts=[query],
            n_results=min(n, count),
            include=["metadatas", "distances"],
        )
        metas     = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]
        if not metas:
            return ""

        lines = []
        for m, dist in zip(metas, distances):
            if dist > _DISTANCE_THRESHOLD:
                continue
            resp_preview = m["response"]
            if len(resp_preview) > 200:
                resp_preview = resp_preview[:200] + "..."
            lines.append(
                f'• You were asked: "{m["query"]}"\n'
                f'  You replied: "{resp_preview}"'
            )

        if not lines:
            return ""
        return "[Memory] Relevant past interactions:\n" + "\n".join(lines) + "\n---"
    except Exception as e:
        print(f"[RAG] Query failed: {e}")
        return ""
