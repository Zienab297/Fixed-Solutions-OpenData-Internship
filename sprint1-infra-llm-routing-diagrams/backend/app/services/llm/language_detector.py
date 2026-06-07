try:
    from langdetect import LangDetectException, detect
except ModuleNotFoundError:
    LangDetectException = ValueError
    detect = None


def detect_language(text: str) -> str:
    if detect is None:
        return "en"

    try:
        return detect(text)
    except LangDetectException:
        return "en"
