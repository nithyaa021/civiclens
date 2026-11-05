"""Pre-download every Phase-2 model artifact.

Run once before first use so that request-time latency never includes a
download:

    python scripts/warmup_models.py

Artifacts fetched:
- fastembed text embeddings   (paraphrase-multilingual-MiniLM-L12-v2, ONNX)
- fastembed CLIP vision       (Qdrant/clip-ViT-B-32-vision, ONNX)
- faster-whisper ASR          (Systran/faster-whisper-{small,tiny}, CTranslate2)
- NLLB-200-distilled-600M     (Xenova ONNX int8, English translation)
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import get_settings  # noqa: E402


def warmup_embeddings() -> None:
    from fastembed import ImageEmbedding, TextEmbedding

    settings = get_settings()
    print(f"[1/4] text embeddings: {settings.embedding_model}", flush=True)
    model = TextEmbedding(model_name=settings.embedding_model)
    next(iter(model.embed(["warmup"])))  # triggers the download + ONNX load
    print("      text embedding model ready", flush=True)

    print("[2/4] image embeddings: Qdrant/clip-ViT-B-32-vision", flush=True)
    img = ImageEmbedding(model_name="Qdrant/clip-ViT-B-32-vision")
    next(iter(img.embed([Path(__file__).with_name("_warmup.png")])))  # type: ignore[arg-type]
    print("      CLIP vision model ready", flush=True)


def warmup_asr() -> None:
    from faster_whisper import WhisperModel

    settings = get_settings()
    for name in dict.fromkeys([settings.whisper_model, "tiny"]):
        print(f"[3/4] ASR model: {name}", flush=True)
        WhisperModel(name, device="cpu", compute_type="int8")
        print(f"      {name} ready", flush=True)


def warmup_translation() -> None:
    from huggingface_hub import snapshot_download

    settings = get_settings()
    print(f"[4/4] translation model: {settings.translation_model}", flush=True)
    path = snapshot_download(
        repo_id=settings.translation_model,
        allow_patterns=[
            "config.json",
            "generation_config.json",
            "tokenizer.json",
            "tokenizer_config.json",
            "special_tokens_map.json",
            "onnx/encoder_model_quantized.onnx",
            "onnx/decoder_model_merged_quantized.onnx",
        ],
        local_dir=settings.translation_local_dir,
    )
    onnx_dir = Path(path) / "onnx"
    files = sorted(p.name for p in onnx_dir.glob("*.onnx")) if onnx_dir.exists() else []
    print(f"      downloaded to {path}", flush=True)
    print(f"      onnx files: {files}", flush=True)


def main() -> int:
    # Small PNG so the image-embedding warmup has a real file to read.
    from PIL import Image

    warmup_png = Path(__file__).with_name("_warmup.png")
    if not warmup_png.exists():
        Image.new("RGB", (64, 64), (120, 160, 90)).save(warmup_png)

    warmup_embeddings()
    warmup_asr()
    warmup_translation()
    print("All Phase-2 models are cached and ready.", flush=True)
    warmup_png.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
