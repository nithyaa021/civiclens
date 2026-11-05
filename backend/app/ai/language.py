"""Hybrid language detection for English / Hindi / Kannada.

Two complementary techniques, chosen by what the text actually is:

1. **Script ranges** - Kannada (U+0C80..U+0CFF) and Devanagari
   (U+0900..U+097F) are unambiguous; the dominant script decides.  This is
   the reliable path for Hindi and Kannada in their native scripts.
2. **lingua** (statistical n-gram detector) - used for Latin-script text
   where script gives no signal (English vs. transliterated Hindi).

Honest limitation: Hindi transliterated into Latin script is usually
detected as English (the lingua Hindi model is Devanagari-based); the
original text is always stored unchanged, so nothing is lost.
"""

from __future__ import annotations

import threading

from app.models.complaint import LanguageInfo

KANNADA_RANGE = (0x0C80, 0x0CFF)
DEVANAGARI_RANGE = (0x0900, 0x097F)

# Dominant-script threshold: a script must own at least this share of the
# letters before it decides the language on its own.
SCRIPT_MIN_RATIO = 0.30

LANGUAGE_NAMES: dict[str, str] = {
    "en": "English",
    "hi": "Hindi",
    "kn": "Kannada",
    "ur": "Urdu",
    "bn": "Bengali",
    "ta": "Tamil",
    "te": "Telugu",
    "mr": "Marathi",
    "gu": "Gujarati",
    "pa": "Punjabi",
    "ml": "Malayalam",
}

_detector = None
_detector_lock = threading.Lock()


def _get_detector():  # noqa: ANN202 - lingua's detector type is a Rust extension
    global _detector
    if _detector is None:
        with _detector_lock:
            if _detector is None:
                from lingua.lingua import Language, LanguageDetectorBuilder

                _detector = LanguageDetectorBuilder.from_languages(
                    Language.ENGLISH, Language.HINDI
                ).build()
    return _detector


def _script_ratio(text: str, bounds: tuple[int, int]) -> float:
    letters = [char for char in text if char.isalpha()]
    if not letters:
        return 0.0
    low, high = bounds
    return sum(1 for char in letters if low <= ord(char) <= high) / len(letters)


def language_name(code: str) -> str:
    """Human label for a language code (falls back to the code itself)."""
    return LANGUAGE_NAMES.get(code, code)


def detect_language(text: str) -> LanguageInfo:
    """Detect the language of ``text``; never raises.

    Returns a :class:`LanguageInfo` with the detector that decided
    (``script`` or ``lingua``) and a confidence in ``[0, 1]``.
    """
    kn_ratio = _script_ratio(text, KANNADA_RANGE)
    dev_ratio = _script_ratio(text, DEVANAGARI_RANGE)
    letters = [char for char in text if char.isalpha()]
    latin_ratio = (
        sum(1 for char in letters if "a" <= char.lower() <= "z") / len(letters) if letters else 0.0
    )

    # Native-script text: the script itself is the strongest signal.
    if letters:
        dominant = max(
            (("kn", kn_ratio), ("hi", dev_ratio), ("en", latin_ratio)),
            key=lambda pair: pair[1],
        )
        code, ratio = dominant
        if code in ("kn", "hi") and ratio >= SCRIPT_MIN_RATIO:
            return LanguageInfo(
                code=code,
                name=language_name(code),
                confidence=round(min(1.0, ratio), 2),
                method="script",
            )

    # Latin-script (or ambiguous) text: statistical detection.
    detector = _get_detector()
    results = detector.compute_language_confidence_values(text)
    if not results:
        return LanguageInfo(code="en", name="English", confidence=0.0, method="lingua")
    top = results[0]
    code = "hi" if top.language.name == "HINDI" else "en"
    return LanguageInfo(
        code=code,
        name=language_name(code),
        confidence=round(float(top.value), 2),
        method="lingua",
    )
