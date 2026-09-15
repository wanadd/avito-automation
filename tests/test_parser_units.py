from decimal import Decimal
from pathlib import Path

from app.models.enums import ParseStatus
from app.services.parser.colors import extract_color
from app.services.parser.confidence import status_from_confidence
from app.services.parser.identity import build_parsed_identity_key
from app.services.parser.line_detector import classify_line
from app.services.parser.memory import parse_memory
from app.services.parser.model_codes import extract_model_code
from app.services.parser.models import normalize_brand, normalize_model
from app.services.parser.pipeline import parse_price_text
from app.services.parser.prices import parse_price
from app.services.parser.regions import extract_region
from app.services.parser.sections import detect_section
from app.services.parser.types import ParsedLine


def test_apple_section_detection():
    assert detect_section("Apple 🍏").normalized == "Apple"


def test_samsung_section_detection():
    assert detect_section("Samsung 🇰🇷").normalized == "Samsung"


def test_xiaomi_section_detection():
    assert detect_section("Xiaomi 🤖").normalized == "Xiaomi"


def test_emoji_does_not_break_section():
    assert detect_section("🍏 Apple").normalized == "Apple"


def test_region_hk():
    assert extract_region("🇭🇰17 pro max")[1] == "HK"


def test_region_kw():
    assert extract_region("🇰🇼S25 ultra")[1] == "KW"


def test_region_ru():
    assert extract_region("🇷🇺Note 17")[1] == "RU"


def test_memory_pair_12_256():
    assert parse_memory("S25 12/256 black")[:2] == (12, 256)


def test_memory_storage_only_256gb():
    assert parse_memory("iPhone 256GB blue")[:2] == (None, 256)


def test_memory_1tb_is_1024():
    assert parse_memory("iPhone 1TB blue")[:2] == (None, 1024)


def test_price_plain_after_dash():
    assert parse_price("S25 - 65300")[1] == 6530000


def test_price_with_space():
    assert parse_price("S25 - 65 300")[1] == 6530000


def test_price_with_dot():
    assert parse_price("S25 - 65.300")[1] == 6530000


def test_samsung_model_code_s938b():
    assert extract_model_code("S25 ultra S938B 12/256")[0] == "S938B"


def test_samsung_s25_ultra_normalization():
    assert normalize_model("Samsung", "S25 ultra")[1] == "Galaxy S25 Ultra"


def test_apple_iphone_17_pro_max_normalization():
    assert normalize_model("Apple", "17 pro max")[1] == "iPhone 17 Pro Max"


def test_redmi_note_normalization_using_xiaomi_context():
    raw, model, ambiguous = normalize_model("Xiaomi", "Note 17 pro 5g")
    brand_raw, brand = normalize_brand("Xiaomi", model)
    assert raw == "Note 17 pro 5g"
    assert model == "Note 17 Pro 5G"
    assert brand == "Redmi"
    assert not ambiguous


def test_known_color_normalization():
    assert extract_color("S25 silverblue")[1] == "Silver Blue"


def test_unknown_color_not_invented():
    assert extract_color("S25 mysterycolor") == ("mysterycolor", None)


def test_non_product_lines_ignored():
    assert classify_line("https://example.test/catalog", "Apple") == "ignored"


def test_ambiguous_product_like_line_review():
    assert classify_line("17 pro max 256 blue", "Apple") == "review"


def test_real_style_telegram_price_lines_parse_without_known_section():
    result = parse_price_text("🇷🇺Redmi 17 8/256 black - 19500\n🎮 Nintendo Switch lite coral - 15800")
    product_lines = [item for item in result.items if item.price_minor is not None]
    assert len(product_lines) == 2
    assert product_lines[0].raw_line == "🇷🇺Redmi 17 8/256 black - 19500"
    assert product_lines[0].price_minor == 1950000
    assert product_lines[0].storage_gb == 256
    assert product_lines[0].color_normalized == "Black"
    assert product_lines[0].region_code == "RU"


def test_sanitized_real_style_telegram_fixture_preserves_product_rows_and_ignores_noise():
    text = Path("tests/fixtures/telegram_supplier_real_style_price.txt").read_text(encoding="utf-8")
    result = parse_price_text(text)
    product_lines = [item for item in result.items if item.price_minor is not None]
    ignored_lines = [item.raw_line for item in result.items if item.parse_status == ParseStatus.IGNORED]
    assert len(product_lines) == 12
    assert any(item.raw_line == "🇰🇼S25 ultra S938B 12/256 grey - 66200" and item.price_minor == 6620000 for item in product_lines)
    assert any(item.raw_line == "⌚️Watch 8 L325 LTE 40mm graphite - 16500" for item in product_lines)
    assert "+7 999 000 00 00" in ignored_lines
    assert "-----" in ignored_lines


def test_confidence_deterministic():
    first = parse_price_text("Apple\n🇭🇰17 pro max 256GB blue - 114500").items[-1]
    second = parse_price_text("Apple\n🇭🇰17 pro max 256GB blue - 114500").items[-1]
    assert first.parse_confidence == second.parse_confidence


def test_confidence_thresholds():
    parsed = ParsedLine(line_number=1, raw_line="x", parse_confidence=Decimal("0.9800"))
    assert status_from_confidence(parsed) == ParseStatus.PARSED
    partial = ParsedLine(line_number=1, raw_line="x", parse_confidence=Decimal("0.8000"), parse_flags=["UNKNOWN_COLOR"])
    assert status_from_confidence(partial) == ParseStatus.PARTIAL
    review = ParsedLine(line_number=1, raw_line="x", parse_confidence=Decimal("0.7999"))
    assert status_from_confidence(review) == ParseStatus.REVIEW


def test_literal_duplicate_detected():
    result = parse_price_text("Apple\n🇭🇰17 pro max 256 blue - 114500\n🇭🇰17 pro max 256 blue - 114500")
    assert "DUPLICATE_LINE" in result.items[-1].parse_flags


def test_parsed_identity_key_ignores_price():
    first = build_parsed_identity_key(
        brand_normalized="Samsung",
        model_normalized="Galaxy S26",
        manufacturer_model_code="S942B",
        ram_gb=12,
        storage_gb=256,
        color_normalized="Purple",
        region_code="IN",
    )
    second = build_parsed_identity_key(
        brand_normalized="Samsung",
        model_normalized="Galaxy S26",
        manufacturer_model_code="S942B",
        ram_gb=12,
        storage_gb=256,
        color_normalized="Purple",
        region_code="IN",
    )
    assert first == second


def test_same_identity_same_price_not_price_conflict():
    result = parse_price_text("Samsung\n🇮🇳S26 S942B 12/256 violet - 63500\n🇮🇳S26 S942B 12/256 violet - 63500")
    items = [item for item in result.items if item.price_minor]
    assert all("PRICE_CONFLICT" not in item.parse_flags for item in items)


def test_same_identity_different_price_creates_price_conflict():
    result = parse_price_text("Samsung\n🇮🇳S26 S942B 12/256 violet - 63500\n🇮🇳S26 S942B 12/256 violet - 64500")
    items = [item for item in result.items if item.model_normalized == "Galaxy S26"]
    assert len(items) == 2
    assert all(item.parse_status == ParseStatus.CONFLICT for item in items)
    assert all("PRICE_CONFLICT" in item.parse_flags for item in items)
