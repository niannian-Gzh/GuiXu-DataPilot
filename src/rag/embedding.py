"""把文本变成向量：bge-small-zh-v1.5 的 ONNX 推理。

**不用 torch。** 设计里 embedding 的预算是 91MB，而 sentence-transformers
光 CPU 版 torch 就 200MB 起步。ONNX Runtime + tokenizers 加起来不到 20MB，
模型本身就是那 90MB——预算对得上，启动也快。

池化用 CLS（`last_hidden_state[:, 0]`），然后 L2 归一化。归一化之后
内积就是余弦相似度，FAISS 那边直接用 `IndexFlatIP`，不用再算距离。
"""

from __future__ import annotations

import threading

import numpy as np

from rag import DIM, MODEL_DIR, RagError

_lock = threading.Lock()
_session = None
_tokenizer = None
_input_names: list[str] = []

# 一批最多多少条。分块后一次几十上百条，全塞进去内存会尖一下；
# 分批对总耗时几乎没影响
BATCH = 16


def available() -> bool:
    return (MODEL_DIR / "model.onnx").exists() and (MODEL_DIR / "tokenizer.json").exists()


def _load():
    global _session, _tokenizer, _input_names
    if _session is not None:
        return

    if not available():
        raise RagError(
            f"embedding 模型不在 {MODEL_DIR}。"
            "运行 `uv run python scripts/fetch_model.py` 下载（约 91MB）"
        )

    import onnxruntime as ort
    from tokenizers import Tokenizer

    session = ort.InferenceSession(
        str(MODEL_DIR / "model.onnx"), providers=["CPUExecutionProvider"],
    )
    tokenizer = Tokenizer.from_file(str(MODEL_DIR / "tokenizer.json"))
    tokenizer.enable_truncation(max_length=512)
    tokenizer.enable_padding(pad_id=0, pad_token="[PAD]")

    _session, _tokenizer = session, tokenizer
    _input_names = [i.name for i in session.get_inputs()]


def encode(texts: list[str]) -> np.ndarray:
    """返回 (n, 512) 的 float32，已归一化。"""
    if not texts:
        return np.zeros((0, DIM), dtype=np.float32)

    with _lock:
        _load()

    vectors = []
    for start in range(0, len(texts), BATCH):
        batch = texts[start:start + BATCH]
        encodings = _tokenizer.encode_batch(batch)
        length = len(encodings[0].ids)

        feed = {}
        for name in _input_names:
            if name == "input_ids":
                feed[name] = np.array([e.ids for e in encodings], dtype=np.int64)
            elif name == "attention_mask":
                feed[name] = np.array([e.attention_mask for e in encodings], dtype=np.int64)
            else:
                # token_type_ids 之类：单句输入全是 0
                feed[name] = np.zeros((len(batch), length), dtype=np.int64)

        hidden = _session.run(None, feed)[0]
        cls = hidden[:, 0, :].astype(np.float32)
        norms = np.linalg.norm(cls, axis=1, keepdims=True)
        vectors.append(cls / np.clip(norms, 1e-12, None))

    out = np.vstack(vectors)
    if out.shape[1] != DIM:
        raise RagError(f"模型输出维度是 {out.shape[1]}，和约定的 {DIM} 不一致")
    return out
