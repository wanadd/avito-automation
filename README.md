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
