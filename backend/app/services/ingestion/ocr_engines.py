"""
OCR engine routing.

Default engine: PaddleOCR's detection + recognition models, exported to
ONNX and run entirely through ONNX Runtime via the `rapidocr_onnxruntime`
package. Both stages (text detection and text recognition) run on ONNX --
this is not a lightweight pre-check, it's the same PP-OCR models Paddle
ships, just without the PaddlePaddle native inference engine (which is what
caused the numpy/opencv dependency conflicts in Sprint 1). For non-Arabic
text this ONNX-Paddle result is the final output.

Language routing: after the ONNX-Paddle pass produces text, we run general
language detection (langdetect) on it. If the detected language is Arabic
-- or the text is empty/too short for langdetect to commit to anything,
which can itself mean the model misread a script it isn't tuned for -- we
re-run the same image through Surya, which has stronger Arabic recognition,
and use that result instead.

Both engines are lazily loaded, process-wide singletons, so model weights
load once per process.
"""
from __future__ import annotations

import re

import numpy as np

# Cheap backup signal alongside langdetect: Unicode ranges covering Arabic
# script (Arabic, Supplement, Extended-A, Presentation Forms A/B). Used when
# OCR output is too short/noisy for langdetect to confidently classify.
_ARABIC_RANGES = (
    (0x0600, 0x06FF),
    (0x0750, 0x077F),
    (0x08A0, 0x08FF),
    (0xFB50, 0xFDFF),
    (0xFE70, 0xFEFF),
)
_ARABIC_CHAR_THRESHOLD = 0.15
_ALPHA_RE = re.compile(r"[^\W\d_]", re.UNICODE)

# langdetect needs a few characters of real text to be reliable. Below this,
# trust the Unicode-range check (or treat as "needs Surya" if also empty).
_MIN_CHARS_FOR_LANGDETECT = 8


def _is_arabic_char(ch: str) -> bool:
    code = ord(ch)
    return any(start <= code <= end for start, end in _ARABIC_RANGES)


def _arabic_char_ratio(text: str) -> float:
    alpha_chars = [c for c in text if _ALPHA_RE.match(c)]
    if not alpha_chars:
        return 0.0
    arabic_count = sum(1 for c in alpha_chars if _is_arabic_char(c))
    return arabic_count / len(alpha_chars)


def detect_language(text: str) -> str:
    """General language detection, not Arabic-specific.

    Returns an ISO 639-1 code (e.g. "en", "fr", "ar"), or "" if no language
    could be determined (empty text, or text too short/ambiguous).
    """
    stripped = text.strip()
    if len(stripped) < _MIN_CHARS_FOR_LANGDETECT:
        return ""

    from langdetect import LangDetectException, detect

    try:
        return detect(stripped)
    except LangDetectException:
        return ""


def needs_surya(text: str) -> bool:
    """Decide whether to re-run this image through Surya.

    True if the OCR output is empty (the ONNX-Paddle models may simply have
    failed to read a script they're not tuned for), or if either general
    language detection or the Arabic Unicode-range backup signal indicates
    Arabic.
    """
    stripped = text.strip()
    if not stripped:
        return True

    language = detect_language(stripped)
    if language == "ar":
        return True
    if language:
        # langdetect committed to a non-Arabic language; trust it.
        return False

    # langdetect couldn't decide (text too short/ambiguous) - fall back to
    # the Unicode-range heuristic.
    return _arabic_char_ratio(stripped) >= _ARABIC_CHAR_THRESHOLD


_PADDLE_ONNX_ENGINE = None


def _get_paddle_onnx_engine():
    """PaddleOCR's PP-OCR det+rec models, running fully on ONNX Runtime."""
    global _PADDLE_ONNX_ENGINE
    if _PADDLE_ONNX_ENGINE is None:
        from rapidocr_onnxruntime import RapidOCR

        _PADDLE_ONNX_ENGINE = RapidOCR()
    return _PADDLE_ONNX_ENGINE


def _run_paddle_onnx(img_array: np.ndarray) -> str:
    engine = _get_paddle_onnx_engine()
    result, _elapse = engine(img_array)

    if not result:
        return ""

    lines = [item[1].strip() for item in result if item and item[1] and item[1].strip()]
    return "\n".join(lines)


_SURYA_RECOGNITION_PREDICTOR = None
_SURYA_DETECTION_PREDICTOR = None


def _get_surya_predictors():
    global _SURYA_RECOGNITION_PREDICTOR, _SURYA_DETECTION_PREDICTOR
    if _SURYA_RECOGNITION_PREDICTOR is None:
        from surya.detection import DetectionPredictor
        from surya.recognition import RecognitionPredictor

        _SURYA_DETECTION_PREDICTOR = DetectionPredictor()
        _SURYA_RECOGNITION_PREDICTOR = RecognitionPredictor()
    return _SURYA_RECOGNITION_PREDICTOR, _SURYA_DETECTION_PREDICTOR


def _run_surya(img_array: np.ndarray) -> str:
    from PIL import Image

    recognition_predictor, detection_predictor = _get_surya_predictors()
    image = Image.fromarray(img_array)

    predictions = recognition_predictor(
        [image],
        [["ar"]],
        detection_predictor,
    )

    lines: list[str] = []
    for page_result in predictions:
        for line in page_result.text_lines:
            if line.text and line.text.strip():
                lines.append(line.text.strip())

    return "\n".join(lines)


def run_ocr(img_array: np.ndarray) -> str:
    """Run OCR on an RGB numpy array.

    1. Full ONNX-Paddle pass (detection + recognition, both on ONNX
       Runtime) - this is the real result, not a pre-check.
    2. General language detection on that text.
    3. If Arabic (or undetectable/empty) -> re-run with Surya and prefer
       that result. Otherwise the ONNX-Paddle result stands as final.
    """
    paddle_text = _run_paddle_onnx(img_array)

    if needs_surya(paddle_text):
        surya_text = _run_surya(img_array)
        if surya_text.strip():
            return surya_text

    return paddle_text