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
- Missing condition is unknown, not `NEW`. Unknown condition can match another unknown-condition variant by the other strong attributes, but it does not exact-match known `NEW`, `USED`, or `REFURBISHED` variants.

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
- Supplier default condition configuration is not implemented yet. Only a future explicit supplier/source default may convert missing condition into a concrete condition.

## Supplier Snapshot & Availability v1

Sprint 0.4 adds supplier snapshot ingestion on top of parser and matcher output. A `SupplierSnapshot` represents one supplier/source raw price-list run and has type `FULL` or `PARTIAL`.

API:

- `POST /api/v1/supplier-snapshots` creates or reuses a snapshot for the same supplier/source/raw record.
- `POST /api/v1/supplier-snapshots/{snapshot_id}/process` parses, matches, records per-line snapshot items, and applies availability rules.
- `GET /api/v1/supplier-snapshots` lists snapshots with optional supplier/source/status/type filters.
- `GET /api/v1/supplier-snapshots/{snapshot_id}` reads one snapshot.
- `GET /api/v1/supplier-snapshots/{snapshot_id}/items` reads the per-line processing result.

Availability policy:

- Seen offers in a processed snapshot move to `IN_STOCK` and reset `consecutive_missing_count`.
- In a valid `FULL` snapshot, supplier offers absent from the snapshot increment `consecutive_missing_count`.
- The first missing full snapshot moves an in-stock or unknown offer to `SUSPECT_MISSING`.
- At `SUPPLIER_MISSING_SNAPSHOTS_TO_OUT_OF_STOCK` consecutive missing full snapshots, the offer moves to `OUT_OF_STOCK`.
- A later seen offer restores to `IN_STOCK` and records a restore audit event.
- `PARTIAL` snapshots update only seen offers and never mark absent offers missing.
- Older snapshots do not overwrite newer availability decisions.

Quality gate:

Malformed or empty `FULL` snapshots are rejected before stockout logic runs. Rejected snapshots keep per-line evidence, but they do not mark existing offers missing or out of stock.

Idempotency and concurrency:

Snapshot creation is idempotent by supplier/source/raw record. Processing a completed or rejected snapshot is read-only. Active processing is serialized by snapshot id so concurrent requests do not duplicate offers or line items.

## Generic Content & Listing Engine

Sprint 0.9 adds an internal preparation pipeline for marketplace-ready content without pretending that the Avito listing contract is known:

```text
ProductVariant
-> ProductContentFacts
-> ProductContentDraft
-> ProductImageSet
-> GenericListingDraft
-> Review / Approval
```

The fact layer stores only trusted structured evidence with provenance and a deterministic `fact_hash`. AI output is not a valid factual source. Missing values remain unknown; for example nullable `ProductVariant.condition` stays `UNKNOWN` in content facts and is never defaulted to `NEW`.

The copy layer can phrase and organize confirmed facts through the deterministic provider. It must not invent condition, warranty, package contents, region, availability, price, authenticity, certification, delivery, or other factual claims. Generated or manually edited drafts are validated against structured facts and high-risk unsupported claims before approval.

The generic listing layer is internal. `generic_category` and `generic_attributes` are not Avito category IDs or Avito field names. `GENERIC READY` means approved content, approved images, valid current price, and acceptable stock/pricing state.

`GENERIC READY` does not mean `AVITO READY`. The Avito adapter boundary exists only as a disabled interface and returns `DISABLED_CONTRACT_INCOMPLETE` until the Avito contract gate passes. Sprint 0.9 does not publish, prepare fake Avito payloads, call Avito, or add Avito publication endpoints.

## Control Layer & Publication Orchestration

Sprint 1.0 adds the operational layer around approved generic listings:

```text
APPROVED GenericListingDraft
-> PublicationIntent
-> PublicationJob
-> PublicationAttempt
-> internal prepared marketplace representation
-> DRY_RUN_SUCCESS or BLOCKED
```

Publication orchestration is separate from `GenericListingDraft`. `MarketplaceListingBinding` records the internal relationship to a marketplace, but Sprint 1.0 never creates a fake `external_listing_id`, never marks a binding `ACTIVE_EXTERNAL`, and never marks anything `SYNCED` from a dry run.

Publication jobs use deterministic idempotency keys based on listing, marketplace, operation, and captured hashes. Every job re-validates the captured listing/content/image/pricing context before processing; stale input is blocked with `STALE_INPUT` and is not silently rebuilt under the old intent.

Dry run builds only an internal normalized representation. It is deliberately marked as not Avito-compatible and includes `contract_status = DISABLED_CONTRACT_INCOMPLETE`. Real Avito execution is centrally blocked with `AVITO_CONTRACT_INCOMPLETE`; there are no live Avito HTTP mutations in Sprint 1.0.

Control API:

- `GET /api/v1/control/overview`
- `GET /api/v1/control/review-queue`
- `GET /api/v1/control/listings`
- `POST /api/v1/control/listings/{listing_id}/publication-intents`
- `POST /api/v1/control/listings/{listing_id}/dry-run`
- `GET /api/v1/control/publication-jobs`
- `POST /api/v1/control/publication-jobs/{job_id}/retry`
- `POST /api/v1/control/publication-jobs/{job_id}/cancel`
- `POST /api/v1/control/reconcile`
- `GET /api/v1/control/bindings`
- `GET /api/v1/control/alerts`

Telegram operator commands are implemented as a control surface over the same backend services: `/status`, `/review`, `/ready`, `/blocked`, `/errors`, `/jobs`, `/help`, and `/dryrun <listing_id>`. Admin actions require `TELEGRAM_OPERATOR_IDS`; IDs are configured through environment variables and are not hardcoded.

Configuration:

- `AUTO_PREPARE_PUBLICATION`, default `false`
- `PUBLICATION_MAX_ATTEMPTS`, default `1`
- `PUBLICATION_RETRY_BASE_SECONDS`, default `60`
- `TELEGRAM_OPERATOR_IDS`, comma-separated operator IDs

NO LIVE AVITO MUTATIONS IN SPRINT 1.0.

## Telegram Supplier Collector v1

Sprint 0.5 adds a Telegram MTProto collector using Telethon. Telegram becomes a raw evidence source only:

```text
Telegram message
-> RawSourceRecord
-> RawSourceRecordRevision
-> SupplierSnapshot
-> parser
-> matcher
-> SupplierOffer
-> availability state machine
```

The collector does not parse SKUs, match products, change offers directly, make pricing decisions, call Avito or 1C, use OCR, use AI, run a scheduler, or listen for real-time `NewMessage` events.

Configuration:

- `TELEGRAM_API_ID`
- `TELEGRAM_API_HASH`
- `TELEGRAM_SESSION_PATH`, default `/data/telegram/session`
- `TELEGRAM_COLLECTOR_ENABLED`, default `false`
- `TELEGRAM_COLLECTOR_POLL_SECONDS`, default `300`
- `TELEGRAM_BACKFILL_LIMIT`, default `50`

Local manual login:

1. Create Telegram API credentials on the official Telegram developer portal.
2. Put only local placeholder values in `.env`, never real values in Git.
3. Run `python scripts/telegram_login.py`.
4. Complete phone, OTP, and optional 2FA interactively.
5. Confirm the session file exists only under `runtime/telegram/` or another ignored runtime path.
6. Configure a `TELEGRAM` source with `external_chat_id` when known, or `username` for first resolution.
7. Call `POST /api/v1/sources/{source_id}/telegram-test`.
8. Run a small backfill with `POST /api/v1/sources/{source_id}/collect`.

Source setup:

Telegram source configuration lives on `Source`; there is no separate TelegramSource table. A source stores `external_chat_id`, optional cached `username` and `title`, `telegram_enabled`, explicit `snapshot_type`, and collection cursor/status fields. `external_chat_id` is the canonical identity because usernames can change. If a username resolves successfully, the numeric chat id is cached back to the source.

Collection APIs:

- `POST /api/v1/sources/{source_id}/collect` with `BACKFILL` or `INCREMENTAL`.
- `POST /api/v1/sources/{source_id}/telegram-test` resolves the configured chat and returns only non-sensitive metadata.
- `GET /api/v1/telegram-collection-runs` lists run history.
- `GET /api/v1/telegram-collection-runs/{run_id}` reads one run.

Backfill and incremental:

Backfill fetches at most the requested limit, or `TELEGRAM_BACKFILL_LIMIT`. Incremental fetches messages after `Source.last_collected_message_id`. Messages are processed oldest to newest even if Telegram returns newest first. The cursor advances only after the message has been safely persisted or safely classified as ignored. Downstream snapshot failures do not cause the same Telegram message to be saved as a new raw record.

Evidence and edits:

`RawSourceRecord` is the logical Telegram message keyed by `source_id + external_record_id`, where `external_record_id` is the Telegram message id. `RawSourceRecordRevision` stores immutable raw content revisions with deterministic SHA-256 over raw text only. A changed Telegram edit creates a new revision and a new `SupplierSnapshot` linked to that exact revision. Original raw text is not overwritten silently.

Message eligibility:

Only non-empty text or caption content is sent downstream. Service messages, empty messages, media-only messages without caption, join/leave/pin events, and reactions are ignored. Media files are not downloaded; metadata records whether media existed and its type.

Failure safety:

Unauthorized sessions, inaccessible channels, network failures, and rate limits produce failed or partial collection runs and sanitized source status. They do not create empty FULL snapshots and do not modify inventory. Deleted Telegram posts are not treated as supplier stock removal in v1.

Security:

Telegram API id/hash, phone number, OTP, 2FA password, session strings, and session files must stay outside Git and logs. `runtime/telegram/` is ignored, Docker mounts it as `/data/telegram`, and `.dockerignore` excludes Telegram session artifacts from the image build context.

CLI:

```bash
python -m app.integrations.telegram.cli collect --source-id <source_uuid> --mode INCREMENTAL --limit 10
```

The CLI uses existing environment configuration and does not perform interactive login.

Known limitations:

- No Telegram Bot API collector.
- No media download, PDF parsing, image OCR, Avito, 1C, pricing engine, frontend admin, real-time event listener, or auto supplier discovery.
- Real Telegram smoke testing is optional and skipped when credentials are absent.

## Scheduler & Worker v1

Sprint 0.6 adds collection orchestration around the Sprint 0.5 Telegram collector:

```text
Scheduler
-> PostgreSQL SourceCollectionJob
-> Redis RQ queue
-> Worker
-> Telegram collector
-> Raw evidence
-> Supplier snapshot pipeline
```

The API, scheduler, and worker are separate Docker Compose services. The API never runs polling in its startup lifecycle. The queue payload contains only `job_id`; source configuration and credentials are read from PostgreSQL/runtime environment by the worker.

Queue technology:

- RQ backed by Redis.
- Queue name: `source-collection`.
- Redis namespaces: `avito:jobs:*` and `avito:locks:*`.

Source scheduling fields:

- `telegram_enabled` means the source can use the Telegram integration.
- `collection_enabled` means the scheduler may automatically enqueue collection jobs.
- `collection_interval_seconds` overrides `TELEGRAM_DEFAULT_COLLECTION_INTERVAL_SECONDS`, default `600`.
- `next_collection_at` tracks the schedule slot, not just `now + interval`.
- `last_scheduled_at`, `consecutive_failures`, and `last_success_at` support operational status.

Scheduler policy:

- Due Telegram sources create idempotent `SCHEDULED_INCREMENTAL` jobs.
- Repeated ticks for the same source and schedule slot do not create duplicate jobs.
- Missed schedules create one catch-up job, then advance to the next future slot.
- Deterministic per-source jitter spreads queue load without changing the schedule identity.

Worker policy:

- The worker validates job state, acquires a Redis source lock with TTL, checks PostgreSQL for another `RUNNING` job on the same source, marks the job `RUNNING`, calls the existing Telegram collector, links `TelegramCollectionRun`, and finishes as `SUCCEEDED`, `RETRY_WAIT`, `FAILED`, or `SKIPPED`.
- Different sources may run in parallel; one source may not run concurrently.
- Queue redelivery is treated as practical at-least-once execution. Terminal jobs are not executed again, and downstream raw evidence/snapshot processing remains idempotent.

Retry and recovery:

- `COLLECTION_JOB_MAX_ATTEMPTS` defaults to `3`.
- Transient network/rate-limit failures move to `RETRY_WAIT` with backoff of about 30s, 120s, then 300s.
- Auth/access/configuration failures fail the current job without tight retry loops.
- Stale `RUNNING` jobs older than `JOB_STALE_RUNNING_SECONDS`, default `900`, are recovered to retry or failed at max attempts.

Operational APIs:

- `POST /api/v1/sources/{source_id}/collect` now creates a queued manual collection job.
- `GET /api/v1/source-collection-jobs`
- `GET /api/v1/source-collection-jobs/{id}`
- `POST /api/v1/source-collection-jobs/{id}/retry`
- `GET /api/v1/sources/{id}/status`
- `GET /api/v1/operations/status`

Source health:

- `DISABLED`: collection disabled.
- `NEVER_RUN`: no collection outcome yet.
- `HEALTHY`: latest collection succeeded and failure counter is zero.
- `DEGRADED`: one or two consecutive failures.
- `ERROR`: failure count reaches `SOURCE_ERROR_FAILURE_THRESHOLD`, default `3`.
- `stale` is computed from `last_success_at > interval * SOURCE_STALE_MULTIPLIER`.

Stale/error source status never changes `SupplierOffer` availability by itself. Inventory availability changes only through valid `FULL` supplier snapshots.

Known limitations:

- No website collector, Avito, 1C, OCR, LLM, notification system, frontend admin, Kubernetes, or real-time Telegram listener.
- Manual job priority is FIFO in v1.
- Permanent auth/access failures do not silently disable a source.

## 1C Read-only Stock & Cost Import v1

Sprint 0.7 adds a strict read-only 1C export importer for own inventory state. The importer accepts only external JSON or CSV files; it does not connect to a 1C database, file base, COM automation, OData write API, documents, sales, customers, orders, reserves, payments, taxes, or cash-register data.

Supported fields:

- `internal_code` as the stable 1C identity.
- optional `sku` and `barcode`.
- `name` as raw evidence plus normalized name.
- `stock_total` as integer units.
- optional `stock_by_store`.
- `cost` stored as `cost_minor`.
- `currency`, currently `RUB`.
- `updated_at`, with root `exported_at` or import timestamp as fallback.

JSON contract:

```json
{
  "exported_at": "2026-09-11T14:30:00+03:00",
  "source": "1c",
  "items": [
    {
      "internal_code": "000123",
      "sku": "SM-S938B-256-SB",
      "barcode": "880609...",
      "name": "Samsung Galaxy S25 Ultra 12/256 Silverblue",
      "stock_total": 2,
      "cost": "65300.00",
      "currency": "RUB"
    }
  ]
}
```

CSV contract:

```text
internal_code,sku,barcode,name,stock_total,cost,currency,updated_at
```

CSV supports UTF-8, UTF-8 BOM, Windows-1251, comma delimiters, and semicolon delimiters. Cost parsing uses `Decimal` and accepts values such as `65300`, `65300.00`, `65300,00`, and `65 300,00`. Invalid stock, fractional stock, missing `internal_code`, negative cost, unsupported currency, and unknown schema fields are rejected for the row or file; values are never clamped silently.

Import APIs:

- `POST /api/v1/1c/import` with multipart `file`, `mode=FULL|PARTIAL`, and `dry_run=true|false`.
- `GET /api/v1/1c/import-runs`.
- `GET /api/v1/1c/import-runs/{id}`.
- `GET /api/v1/1c/items`.
- `GET /api/v1/1c/items/{id}`.
- `POST /api/v1/1c/items/{id}/map`.
- `DELETE /api/v1/1c/items/{id}/map`.
- `GET /api/v1/inventory`.
- `GET /api/v1/variants/{variant_id}/inventory`.

CLI:

```bash
python -m app.integrations.one_c.cli import-file ./export.json --mode FULL --dry-run
```

Matcher behavior:

- Existing explicit `internal_code -> ProductVariant` mapping wins and is not fuzzy-rematched.
- Exact barcode/SKU matching uses existing variant aliases.
- Exact manufacturer model code and high-confidence deterministic name matching may auto-match.
- Ambiguous candidates are blocked for review.
- Unknown 1C rows create `OneCItem` records as `UNMATCHED`; the importer does not auto-create `Product` or `ProductVariant`.

Inventory behavior:

- Own stock/cost lives in `VariantInventoryState` and is separate from supplier availability in `SupplierOffer`.
- `VariantStockSnapshot` and `VariantCostSnapshot` are written only for first value or actual changes.
- Unchanged rows update source item visibility without history spam.
- Out-of-order imports do not regress current inventory state.
- If stock becomes zero, last known cost is retained.

FULL/PARTIAL safety:

- `PARTIAL` missing rows mean nothing and never zero stock.
- `FULL` missing rows may set own stock to zero only after quality gates.
- Empty or low-quality FULL imports are rejected.
- Mass-zero protection rejects a FULL import when missing mapped active items exceed `ONE_C_MAX_MISSING_RATIO`.
- Dry-run imports report prospective stock, cost, and missing-zero counts without mutating current inventory or history.

Known limitations:

- No direct 1C connection, file watcher, COM, write sync, sales/documents/customers/orders/reserves, Avito, pricing engine, LLM, OCR, or frontend admin.
- SKU and barcode exact matching use `ProductAlias` until the catalog model grows first-class fields.

## Sprint 1.1 Operator UI and Production Readiness

Sprint 1.1 adds a real internal operator application in `apps/web` and closes the control API behind production-oriented operator authentication.

Operator UI routes:

- `/` dashboard with aggregated operational counters.
- `/products` and `/products/[variantId]` for product, supplier, 1C, pricing, facts, content, images, listing, publication, and audit context.
- `/review` for review queue operations.
- `/publication` and `/publication/jobs/[jobId]` for dry-run publication jobs and prepared internal payload inspection.
- `/suppliers`, `/sources`, `/inventory`, `/pricing`, `/alerts`, `/audit`, `/settings`.

Authentication:

- DB-backed `OperatorUser` and `OperatorSession`.
- Argon2id password hashes.
- HttpOnly session cookie.
- CSRF cookie/header for browser mutations.
- Logout revocation and session expiration.
- Roles: `VIEWER`, `OPERATOR`, `ADMIN`.

Create the first admin without storing a default password:

```powershell
docker compose -f docker-compose.prod.yml exec -T api python -m app.cli create-operator admin --role ADMIN
```

Production readiness:

- `.env.example` contains placeholders only.
- `docker-compose.prod.yml` runs PostgreSQL, Redis, API, worker, scheduler, web, and nginx.
- PostgreSQL and Redis are internal-network only in production compose.
- `infra/nginx/avito-automation.conf.template` routes `/` to web, `/api/` to API, and `/health` to API health.
- `scripts/backup.ps1` creates a PostgreSQL backup manifest with 7-day default retention.
- `scripts/deploy-prod.ps1` performs backup, build, start, migration, and health verification before printing `DEPLOY: PASS`.
- `docs/production-runbook.md` documents deploy, backup, restore, worker/scheduler restart, migration, and incident checks.
- `docs/security.md` documents secrets, sessions, operator passwords, Telegram sessions, DB/Redis exposure, backups, and frontend safety.

Live Avito publication remains disabled:

```text
DISABLED_CONTRACT_INCOMPLETE
```

Operators can prepare, dry-run, reconcile, inspect jobs, and review payloads. There is no real Avito OAuth, no mutation, no guessed Autoload schema, no logged-in scraping, and no fake external listing state.
