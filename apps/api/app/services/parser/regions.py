from app.services.parser.constants import KNOWN_FLAG_CHARS, REGION_FLAGS


def extract_region(line: str) -> tuple[str | None, str | None, bool]:
    for flag, code in REGION_FLAGS.items():
        if flag in line:
            return flag, code, False
    has_unknown_flag = any(char in KNOWN_FLAG_CHARS for char in line)
    return None, None, has_unknown_flag

