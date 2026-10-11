"""Names every template must survive: the longest expected names (fit) and names ending with hamza (text proof)."""
from __future__ import annotations

LONGEST_NAMES = {"ar": "عبد الرحمن محمود", "en": "Abdelrahman Ali"}  # 14 letters each (brief §6.2 default)
# Names ending with hamza: glued to the next word by PDF extraction in title fonts (operator report, Lalezar).
HAMZA_NAMES = ("جيداء", "هناء", "أسماء", "شيماء", "علاء", "رجاء")


def language_of(text: str) -> str:
    return "ar" if any("؀" <= c <= "ۿ" for c in text or "") else "en"
