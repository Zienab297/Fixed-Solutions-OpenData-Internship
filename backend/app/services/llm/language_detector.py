"""Simple language detection for multilingual query handling."""
try:
    from langdetect import detect
    def detect_language(text: str) -> str:
        try:
            return detect(text)
        except Exception:
            return "en"
except ImportError:
    def detect_language(text: str) -> str:
        return "en"
