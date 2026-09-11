# avito-automation

Minimal production-oriented backend foundation for Sprint 0.1. This sprint intentionally excludes Avito, Telegram API, 1C, AI/LLM, web UI, site parsing, and sales workflows.

## Stack

- Python 3.12
- FastAPI
- SQLAlchemy 2.x async
- PostgreSQL 16
- Alembic
- Pydantic v2
- Redis 7
- pytest
- Docker Compose

## Run

```bash
docker compose up -d --build
```

API health check:

```bash
curl http://localhost:8000/health
```

## Stop

```bash
docker compose down
```

## Migrations

```bash
docker compose exec api alembic upgrade head
```

For local execution, set `DATABASE_URL` first and run:

```bash
alembic upgrade head
```

## Tests

Integration tests require PostgreSQL semantics and do not use SQLite.

```bash
pytest
```

By default tests read `TEST_DATABASE_URL`; if it is not set, they fall back to `DATABASE_URL`.

## Structure

- `apps/api/app` - FastAPI application, domain models, schemas, services, repositories.
- `alembic` - database migrations.
- `tests` - PostgreSQL-backed integration tests.
- `infra/docker` - API Dockerfile.
- `docker-compose.yml` - local PostgreSQL, Redis, and API services.

## Sprint 0.1 Boundaries

Implemented scope is limited to suppliers, sources, raw records, products, variants, supplier offers, immutable offer snapshots, conflicts, audit logs, and health checks. External integrations and sales/business automation are deliberately out of scope.

## Supplier Price Parser v1

Sprint 0.2 adds a deterministic text parser for supplier Telegram price lists. The parser accepts raw text already saved in `RawSourceRecord`; it does not connect to Telegram, Avito, 1C, websites, LLMs, or external AI APIs.

Pipeline:

```text
Raw price text
-> line tokenizer
-> section detector
-> product-line detector
-> field parser
-> normalizer
-> confidence scorer
-> within-price conflict detector
-> ParsedSupplierItem[]
```

Supported sections:

Apple, Samsung, Xiaomi, Redmi, POCO, Honor, Huawei, Realme, OnePlus, Google, Nothing, Motorola, Tecno, Infinix, Oppo, Vivo. Emoji in section headings is ignored for detection. Unknown/generic lines are not promoted to products automatically.

Region mapping:

- `🇷🇺` -> `RU`
- `🇮🇳` -> `IN`
- `🇭🇰` -> `HK`
- `🇦🇪` -> `AE`
- `🇰🇼` -> `KW`
- `🇪🇺` -> `EU`
- `🇺🇸` -> `US`

Memory parsing supports paired RAM/storage forms such as `12/256`, `8/256GB`, `12/256 Gb`, and storage-only forms such as `256GB` and `1TB`. Storage-only input never invents RAM.

Price parsing supports values after `-`, `—`, or `–`, plus ruble-marked values and common grouping forms such as `65 300` and `65.300`. Prices are stored as integer minor units; floats are not used.

Confidence is deterministic and based on recognized brand/section, model, price, memory, model code, color, region, and ambiguity flags. Thresholds are centralized in parser constants:

- `>= 0.9800`: `PARSED` when no review/conflict flags are present.
- `0.8000` to `0.9799`: `PARTIAL`.
- `< 0.8000`: `REVIEW`.
- `CONFLICT` takes priority over confidence.

Parse flags are machine-readable and include `UNKNOWN_SECTION`, `UNKNOWN_REGION`, `UNKNOWN_COLOR`, `MISSING_PRICE`, `INVALID_PRICE`, `MISSING_MODEL`, `AMBIGUOUS_MODEL`, `AMBIGUOUS_MEMORY`, `POSSIBLE_MODEL_CODE`, `DUPLICATE_LINE`, and `PRICE_CONFLICT`.

Conflict policy:

The parser computes a deterministic `parsed_identity_key` for matching candidates inside one raw price list. Price is not part of this identity. If two lines in one raw record normalize to the same parsed identity with different prices, both lines are marked `CONFLICT`, both receive `PRICE_CONFLICT`, and a `DataConflict` stores both raw lines and prices. The parser does not choose a winning price and does not create or update `SupplierOffer` from conflicting parsed data.

Idempotency:

`POST /api/v1/raw-records/{raw_record_id}/parse` uses transactional replacement of the parsed projection for the immutable `RawSourceRecord`. Repeating parse for the same raw record replaces prior `ParsedSupplierItem` rows and parser-created conflicts instead of appending duplicates.

Parser v1 does not perform final `ProductVariant` matching. It prepares normalized evidence for a later matcher.

## Product Matcher v1

Sprint 0.3 adds a safe deterministic matcher from `ParsedSupplierItem` to catalog entities and supplier offers.

Priority order:

1. Block parser conflicts and invalid/missing prices.
2. Match exact manufacturer model code when brand and variant-defining attributes do not conflict.
3. Match exact ProductAlias, including source-specific aliases.
4. Match exact variant-defining attributes.
5. Generate fuzzy candidates for review only.
6. Safe auto-create Product/ProductVariant when confidence and evidence are strong enough.

Variant-defining attributes:

- Required when available: product identity and storage.
- Significant when present: RAM, manufacturer model code, region, color, condition.
- Region, color, and condition are significant SKU attributes in v1.

Auto-create policy:

`AUTO_CREATE_SAFE` requires parsed status `PARSED` or acceptable `PARTIAL`, known brand, known model, known storage, valid price, no `PRICE_CONFLICT`, no model ambiguity, no similar candidate, and confidence at or above `MATCH_AUTO_CREATE_THRESHOLD`.

Review policy:

Strong identifiers with conflicting attributes do not update catalog data or supplier offers. They create a `MatchReview` with deterministic reasons such as `STORAGE_CONFLICT`, `RAM_CONFLICT`, `COLOR_CONFLICT`, `REGION_CONFLICT`, or `CONDITION_CONFLICT`.

Fuzzy matching:

Fuzzy matching is only used for candidate generation and review routing. Fuzzy matching never performs automatic SKU merge in v1.

SupplierOffer ingestion:

Only `EXACT_MATCH` and `AUTO_CREATED` results call the existing SupplierOffer upsert service. The matcher does not write offers directly, so Sprint 0.1 snapshot and audit behavior remains centralized.

Idempotency and concurrency:

Repeated matching of the same parsed item reuses Product, ProductVariant, SupplierOffer, and MatchReview records. Product uniqueness and ProductVariant canonical keys protect concurrent safe auto-create attempts.

Known limitations:

- No LLM, external AI, Telegram API, Avito API, website scraping, 1C, pricing engine, competitor parser, UI, sales, or accounting integration.
- Matcher v1 is conservative; uncertain or fuzzy cases go to review.
- When parsed condition is missing but auto-create is otherwise safe, v1 creates a `NEW` variant as a temporary matcher policy until supplier default condition configuration exists.
