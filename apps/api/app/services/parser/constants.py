from decimal import Decimal

PARSED_THRESHOLD = Decimal("0.9800")
PARTIAL_THRESHOLD = Decimal("0.8000")

KNOWN_SECTIONS = {
    "apple": "Apple",
    "samsung": "Samsung",
    "xiaomi": "Xiaomi",
    "redmi": "Redmi",
    "poco": "POCO",
    "honor": "Honor",
    "huawei": "Huawei",
    "realme": "Realme",
    "oneplus": "OnePlus",
    "google": "Google",
    "nothing": "Nothing",
    "motorola": "Motorola",
    "tecno": "Tecno",
    "infinix": "Infinix",
    "oppo": "Oppo",
    "vivo": "Vivo",
}

REGION_FLAGS = {
    "🇷🇺": "RU",
    "🇮🇳": "IN",
    "🇭🇰": "HK",
    "🇦🇪": "AE",
    "🇰🇼": "KW",
    "🇪🇺": "EU",
    "🇺🇸": "US",
}

KNOWN_FLAG_CHARS = set("🇦🇪🇪🇺🇭🇰🇮🇳🇰🇼🇷🇺🇺🇸")

COLOR_MAP = {
    "black": "Black",
    "white": "White",
    "blue": "Blue",
    "silver": "Silver",
    "silverblue": "Silver Blue",
    "silver blue": "Silver Blue",
    "grey": "Gray",
    "gray": "Gray",
    "green": "Green",
    "pink": "Pink",
    "purple": "Purple",
    "violet": "Purple",
    "gold": "Gold",
}

IGNORED_PATTERNS = (
    "http://",
    "https://",
    "www.",
    "доставка",
    "delivery",
    "наличие",
    "price",
    "прайс",
    "акция",
    "sale",
)

