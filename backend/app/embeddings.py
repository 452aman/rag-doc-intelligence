import hashlib
import re
import threading

import numpy as np

from app.core.config import get_settings

DIM_HASH = 512


class HashEmbedder:
    """Offline fallback (tests): signed feature hashing over word unigrams + bigrams."""
    dim = DIM_HASH

    def embed(self, texts: list[str]) -> np.ndarray:
        out = np.zeros((len(texts), DIM_HASH), dtype="float32")
        for row, t in enumerate(texts):
            words = re.findall(r"[a-z0-9_]+", t.lower())
            for tok in words + [f"{a}_{b}" for a, b in zip(words, words[1:])]:
                h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
                out[row, h % DIM_HASH] += 1.0 if (h >> 64) & 1 else -1.0
        return out


class FastEmbedder:
    dim = 384

    def __init__(self) -> None:
        from fastembed import TextEmbedding
        self.model = TextEmbedding("BAAI/bge-small-en-v1.5")

    def embed(self, texts: list[str]) -> np.ndarray:
        return np.array(list(self.model.embed(texts)), dtype="float32")


def normalize(v: np.ndarray) -> np.ndarray:
    return v / np.maximum(np.linalg.norm(v, axis=1, keepdims=True), 1e-9)


_lock = threading.Lock()
_embedder = None


def get_embedder():
    global _embedder
    with _lock:
        if _embedder is None:
            _embedder = FastEmbedder() if get_settings().embedding_backend == "fastembed" else HashEmbedder()
        return _embedder
