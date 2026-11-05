"""English translation via NLLB-200-distilled-600M (ONNX Runtime, CPU).

The model runs entirely on onnxruntime - no PyTorch.  Xenova's exported
``decoder_model_merged.onnx`` supports both the cached and cache-free decode
branches; this module uses the cache-free branch with a simple greedy loop
(forcing the target language token as the first generated token, matching
HuggingFace's ``forced_bos_token_id`` behaviour for NLLB).

Batched greedy decode keeps seed-time translation fast: one encoder pass for
the whole batch, then one decoder step per position across all rows.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

import numpy as np

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger("civiclens.ai.translation")

# BCP-47 -> NLLB language code.  Anything outside this map is recorded but
# left untranslated (documented behaviour, never machine-guessed).
SRC_LANG_MAP: dict[str, str] = {
    "en": "eng_Latn",
    "hi": "hin_Deva",
    "kn": "kan_Knda",
    "ur": "urd_Arab",
    "bn": "ben_Beng",
    "ta": "tam_Taml",
    "te": "tel_Telu",
    "mr": "mar_Deva",
    "gu": "guj_Gujr",
    "pa": "pan_Guru",
    "ml": "mal_Mlym",
}


class TranslationError(RuntimeError):
    """Raised when the translation model cannot be initialised or run."""


class NllbTranslator:
    """Lazy, thread-safe NLLB translator bound to onnxruntime."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._ready = False
        self._tokenizer: Any = None
        self._encoder: Any = None
        self._decoder: Any = None
        self._decoder_start: int = 2
        self._pad_id: int = 1
        self._eos_id: int = 2
        self._model_dir: Path | None = None

    # --- setup -----------------------------------------------------
    def _ensure_loaded(self) -> None:
        if self._ready:
            return
        with self._lock:
            if self._ready:
                return
            from huggingface_hub import snapshot_download
            from onnxruntime import InferenceSession, SessionOptions
            from tokenizers import Tokenizer

            settings = get_settings()
            local_dir = Path(settings.translation_local_dir)
            has_local = any(
                (local_dir / "onnx" / name).exists()
                for name in (
                    "encoder_model_quantized.onnx",
                    "encoder_model_int8.onnx",
                    "encoder_model.onnx",
                )
            )
            if has_local:
                model_dir = local_dir
            else:
                model_dir = Path(
                    snapshot_download(
                        repo_id=settings.translation_model,
                        allow_patterns=[
                            "config.json",
                            "generation_config.json",
                            "tokenizer.json",
                            "tokenizer_config.json",
                            "special_tokens_map.json",
                            "onnx/encoder_model_quantized.onnx",
                            "onnx/encoder_model_int8.onnx",
                            "onnx/decoder_model_merged_quantized.onnx",
                            "onnx/decoder_model_merged_int8.onnx",
                        ],
                    )
                )
            onnx_dir = model_dir / "onnx"
            encoder_path = self._pick(
                onnx_dir,
                [
                    "encoder_model_quantized.onnx",
                    "encoder_model_int8.onnx",
                    "encoder_model.onnx",
                ],
            )
            decoder_path = self._pick(
                onnx_dir,
                [
                    "decoder_model_merged_quantized.onnx",
                    "decoder_model_merged_int8.onnx",
                    "decoder_model_merged.onnx",
                ],
            )
            if encoder_path is None or decoder_path is None:
                raise TranslationError(
                    f"translation model files missing under {onnx_dir} "
                    f"(encoder={encoder_path is not None}, decoder={decoder_path is not None})"
                )

            options = SessionOptions()
            options.intra_op_num_threads = 4
            self._encoder = InferenceSession(
                str(encoder_path), options, providers=["CPUExecutionProvider"]
            )
            self._decoder = InferenceSession(
                str(decoder_path), options, providers=["CPUExecutionProvider"]
            )
            self._tokenizer = Tokenizer.from_file(str(model_dir / "tokenizer.json"))

            config = json.loads((model_dir / "config.json").read_text(encoding="utf-8"))
            self._decoder_start = int(config.get("decoder_start_token_id", 2))
            vocab = self._tokenizer.get_vocab()
            self._eos_id = int(config.get("eos_token_id", vocab.get("</s>", 2)))
            self._pad_id = int(config.get("pad_token_id", vocab.get("<pad>", 1)))
            self._model_dir = model_dir
            self._ready = True
            logger.info(
                "translation_model_loaded",
                model=settings.translation_model,
                encoder=encoder_path.name,
                decoder=decoder_path.name,
            )

    @staticmethod
    def _pick(directory: Path, candidates: list[str]) -> Path | None:
        for name in candidates:
            path = directory / name
            if path.exists():
                return path
        return None

    # --- encoding ---------------------------------------------------
    def _encode_batch(
        self, texts: list[str], src_codes: list[str]
    ) -> tuple[np.ndarray, np.ndarray]:
        vocab = self._tokenizer.get_vocab()
        rows: list[list[int]] = []
        for text, src in zip(texts, src_codes, strict=True):
            src_id = vocab.get(src)
            ids = self._tokenizer.encode(text).ids
            # NLLB input = <src_lang> sentence </s>
            if not ids or ids[-1] != self._eos_id:
                ids = [*ids, self._eos_id]
            if src_id is not None and (not ids or ids[0] != src_id):
                ids = [src_id, *ids]
            rows.append(ids)

        max_len = max(len(row) for row in rows)
        input_ids = np.full((len(rows), max_len), self._pad_id, dtype=np.int64)
        attention = np.zeros((len(rows), max_len), dtype=np.int64)
        for i, row in enumerate(rows):
            input_ids[i, : len(row)] = row
            attention[i, : len(row)] = 1
        return input_ids, attention

    # --- generation -------------------------------------------------
    def translate_batch(self, texts: list[str], src_codes: list[str]) -> list[str]:
        """Translate each text to English (greedy decode, batched)."""
        if len(texts) != len(src_codes):
            raise ValueError("texts and src_codes must have the same length")
        if not texts:
            return []
        self._ensure_loaded()

        settings = get_settings()
        input_ids, attention = self._encode_batch(texts, src_codes)
        encoder_outputs = self._encoder.run(
            None, {"input_ids": input_ids, "attention_mask": attention}
        )[0]

        batch = len(texts)
        tgt_id = self._tokenizer.get_vocab().get("eng_Latn")
        if tgt_id is None:
            raise TranslationError("target language token eng_Latn missing from tokenizer vocab")

        seq = np.full((batch, 1), self._decoder_start, dtype=np.int64)
        finished = np.zeros(batch, dtype=bool)
        decoder_names = {inp.name for inp in self._decoder.get_inputs()}

        for step in range(settings.translation_max_tokens):
            feeds: dict[str, np.ndarray] = {"input_ids": seq}
            if "attention_mask" in decoder_names:
                feeds["attention_mask"] = np.ones_like(seq, dtype=np.int64)
            if "encoder_hidden_states" in decoder_names:
                feeds["encoder_hidden_states"] = encoder_outputs
            if "encoder_attention_mask" in decoder_names:
                feeds["encoder_attention_mask"] = attention
            if "use_cache_branch" in decoder_names:
                feeds["use_cache_branch"] = np.zeros((1,), dtype=bool)
            # Optional cache inputs (only consumed on the cache branch).
            for name in decoder_names:
                if name.startswith("past_key_values") and name not in feeds:
                    shape = self._decoder.get_inputs()[
                        [i.name for i in self._decoder.get_inputs()].index(name)
                    ].shape
                    dims = [d if isinstance(d, int) and d > 0 else 1 for d in shape]
                    dims[0] = batch
                    feeds[name] = np.zeros(dims, dtype=np.float32)

            logits = self._decoder.run(None, feeds)[0][:, -1, :]  # (batch, vocab)
            if step == 0:
                # forced_bos_token_id: first generated token = target language.
                forced = np.full_like(logits, -1e9)
                forced[:, tgt_id] = logits[:, tgt_id]
                logits = forced
            next_ids = np.argmax(logits, axis=-1).astype(np.int64)
            next_ids[finished] = self._pad_id
            seq = np.concatenate([seq, next_ids[:, None]], axis=1)
            finished |= next_ids == self._eos_id
            if bool(finished.all()):
                break

        outputs: list[str] = []
        for i in range(batch):
            row = seq[i, 1:].tolist()  # drop decoder start token
            row = [tok for tok in row if tok not in (self._pad_id, self._eos_id)]
            outputs.append(self._tokenizer.decode(row).strip())
        return outputs


_translator: NllbTranslator | None = None
_translator_lock = threading.Lock()


def get_translator() -> NllbTranslator:
    global _translator
    if _translator is None:
        with _translator_lock:
            if _translator is None:
                _translator = NllbTranslator()
    return _translator


def translate_to_english(texts: list[str], src_codes: list[str]) -> list[str]:
    """Translate texts to English; texts whose source is unknown or already
    English are returned unchanged (callers store ``None`` for English)."""
    if len(texts) != len(src_codes):
        raise ValueError("texts and src_codes must have the same length")

    results: list[str] = [""] * len(texts)
    todo_idx: list[int] = []
    todo_texts: list[str] = []
    todo_codes: list[str] = []

    for i, (text, code) in enumerate(zip(texts, src_codes, strict=True)):
        nllb_code = SRC_LANG_MAP.get(code)
        if not text.strip() or nllb_code is None or code == "en":
            results[i] = text
            continue
        todo_idx.append(i)
        todo_texts.append(text)
        todo_codes.append(nllb_code)

    if todo_texts:
        translated = get_translator().translate_batch(todo_texts, todo_codes)
        for i, value in zip(todo_idx, translated, strict=True):
            results[i] = value
    return results
