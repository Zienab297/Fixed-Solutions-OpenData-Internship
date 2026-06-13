try:
    from langdetect import LangDetectException, detect, detect_langs
except ModuleNotFoundError:
    LangDetectException = ValueError
    detect = None
    detect_langs = None


def detect_language(text: str) -> str:
    if detect is None or len(text.strip()) < 20:
        return "en"

    try:
        langs = detect_langs(text)
        top = langs[0]
        if top.prob < 0.90:
            return "en"
        return top.lang
    except LangDetectException:
        return "en"