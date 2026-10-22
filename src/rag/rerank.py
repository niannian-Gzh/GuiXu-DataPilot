"""精排接口：**留形状，权重按需下**。

设计里对这一层的定位是"质量增强，没有它链路照样完整"：
- 向量召回（bge-small-zh）负责"从几千块里捞出可能相关的几十块"
- reranker 负责"在这几十块里排准前 k 条"

所以没有权重时**必须能正常返回**——直接把向量排序的结果给回去，
不报错、不降级成空。

权重放在 `models/gte-multilingual-reranker-base/`（`model.onnx` +
`tokenizer.json`）。**注意：`Alibaba-NLP/gte-multilingual-reranker-base`
没有公开的 ONNX 导出**（原仓库是 safetensors，Xenova 也没有转好的版本），
所以要启用精排得自己用 optimum 导出一次；不导出就永远不会走到 ONNX 分支。
这里不假装提供一个下不了的下载入口。

跨编码器（cross-encoder）和双塔不一样：它把 (query, passage) 拼成一对
一起过模型，所以分数不是余弦，**不能拿 `rag.min_score` 去卡它**——
那个阈值只管向量召回。
"""

from __future__ import annotations

import threading

from config import RESOURCE_ROOT

MODEL_DIR = RESOURCE_ROOT / "models" / "gte-multilingual-reranker-base"

_lock = threading.Lock()
_session = None
_tokenizer = None


def available() -> bool:
    return (MODEL_DIR / "model.onnx").exists() and (MODEL_DIR / "tokenizer.json").exists()


def _load():
    global _session, _tokenizer
    if _session is not None:
        return

    import onnxruntime as ort
    from tokenizers import Tokenizer

    _session = ort.InferenceSession(
        str(MODEL_DIR / "model.onnx"), providers=["CPUExecutionProvider"],
    )
    _tokenizer = Tokenizer.from_file(str(MODEL_DIR / "tokenizer.json"))
    _tokenizer.enable_truncation(max_length=512)
    _tokenizer.enable_padding(pad_id=0, pad_token="[PAD]")


def rerank(query: str, candidates: list[dict], top_k: int) -> list[dict]:
    """按相关度重排候选，返回前 top_k。

    没有权重时返回原顺序的前 top_k——调用方不需要知道有没有装。
    """
    if not candidates or not available():
        return candidates[:top_k]

    import numpy as np

    with _lock:
        _load()

    encodings = _tokenizer.encode_batch([
        (query, c.get("text") or "") for c in candidates
    ])
    length = len(encodings[0].ids)
    feed = {}
    for inp in _session.get_inputs():
        if inp.name == "input_ids":
            feed[inp.name] = np.array([e.ids for e in encodings], dtype=np.int64)
        elif inp.name == "attention_mask":
            feed[inp.name] = np.array([e.attention_mask for e in encodings], dtype=np.int64)
        else:
            feed[inp.name] = np.zeros((len(encodings), length), dtype=np.int64)

    logits = _session.run(None, feed)[0]
    scores = np.asarray(logits).reshape(len(candidates), -1)[:, 0]

    order = sorted(range(len(candidates)), key=lambda i: float(scores[i]), reverse=True)
    out = []
    for i in order[:top_k]:
        item = dict(candidates[i])
        item["rerank_score"] = round(float(scores[i]), 4)
        out.append(item)
    return out
