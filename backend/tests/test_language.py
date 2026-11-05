"""Language detection and NLLB translation plumbing."""

from __future__ import annotations

import pytest

from app.ai.language import detect_language, language_name
from app.ai.translation import SRC_LANG_MAP, translate_to_english

KANNADA = "ರಸ್ತೆಯಲ್ಲಿ ಆಳವಾದ ಗುಂಡಿ ರಸ್ತೆಯ ಮಧ್ಯದಲ್ಲಿದೆ"
HINDI = "सड़क पर गहरा गड्ढा है और दोपहिया वाहन फिसल रहे हैं"
ENGLISH = "Deep pothole on the main road near the school gate"


def test_script_detection_for_kannada_and_hindi() -> None:
    kannada = detect_language(KANNADA)
    assert kannada.code == "kn"
    assert kannada.method == "script"
    assert kannada.name == "Kannada"
    assert kannada.confidence >= 0.3

    hindi = detect_language(HINDI)
    assert hindi.code == "hi"
    assert hindi.method == "script"
    assert hindi.name == "Hindi"


def test_latin_script_falls_back_to_lingua() -> None:
    result = detect_language(ENGLISH)
    assert result.code == "en"
    assert result.method == "lingua"


def test_language_name_lookup() -> None:
    assert language_name("kn") == "Kannada"
    assert language_name("hi") == "Hindi"
    assert language_name("xx") == "xx"


def test_translation_passthrough_for_english_and_unknown_codes() -> None:
    assert translate_to_english(["Hello"], ["en"]) == ["Hello"]
    assert translate_to_english(["Unmapped text"], ["xx"]) == ["Unmapped text"]
    assert translate_to_english(["  "], ["hi"]) == ["  "]


def test_translation_length_mismatch_is_rejected() -> None:
    with pytest.raises(ValueError):
        translate_to_english(["a", "b"], ["hi"])


def test_supported_source_languages_map_to_nllb_codes() -> None:
    assert SRC_LANG_MAP["hi"] == "hin_Deva"
    assert SRC_LANG_MAP["kn"] == "kan_Knda"


def test_kannada_is_translated_to_english() -> None:
    [translated] = translate_to_english([KANNADA], ["kn"])
    assert translated.strip()
    assert translated != KANNADA
    assert any(char.isascii() and char.isalpha() for char in translated), translated
