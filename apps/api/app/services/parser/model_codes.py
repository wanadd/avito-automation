import re


MODEL_CODE_RE = re.compile(r"\b(?P<code>[A-Z]\d{3,4}[A-Z]{0,2})\b")
POSSIBLE_CODE_RE = re.compile(r"\b(?=[A-Za-z]*\d)(?=[A-Za-z\d]*[A-Za-z])[A-Za-z\d]{4,8}\b")


def extract_model_code(line: str) -> tuple[str | None, bool]:
    matches = MODEL_CODE_RE.findall(line)
    if len(matches) == 1:
        return matches[0], False
    if len(matches) > 1:
        return matches[0], True
    possible = POSSIBLE_CODE_RE.findall(line)
    return None, bool(possible)


def remove_model_code(line: str, code: str | None) -> str:
    if code is None:
        return line
    return re.sub(rf"\b{re.escape(code)}\b", " ", line)

