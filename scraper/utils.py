import re
from typing import Optional, List

def normalize_text(s: Optional[str]) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"[|–—\-_:;,./\\]+", " ", s)
    s = re.sub(r"\([^)]*\)", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def uniq_list(items: List[str]) -> List[str]:
    out = []
    seen = set()
    for x in items:
        n = normalize_text(x)
        if n and n not in seen:
            seen.add(n)
            out.append(x.strip())
    return out
