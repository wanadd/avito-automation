import re

from app.models.enums import ProductCondition


def extract_condition(line: str) -> ProductCondition | None:
    if re.search(r"\b(used|б/у|бу)\b", line, re.IGNORECASE):
        return ProductCondition.USED
    if re.search(r"\b(refurbished|refurb)\b", line, re.IGNORECASE):
        return ProductCondition.REFURBISHED
    return None

