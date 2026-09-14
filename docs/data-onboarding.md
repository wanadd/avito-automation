# Real Data Onboarding

Sprint 1.2 uses a preview-and-confirm workflow for real operational inputs. Preview steps are safe for operators: Telegram preview parses pasted text without creating supplier offers, and 1C preview runs the existing importer in `dry_run=true` mode.

## Telegram Manual Fallback

Use the operator UI at `/imports/telegram` or call:

```bash
POST /api/v1/onboarding/telegram/preview
POST /api/v1/onboarding/telegram/{batch_id}/confirm
```

Preview returns candidate line counts, valid item counts, computed ratio, parsed condition, price, model evidence, and parse flags. Confirm creates a raw source record with preserved raw evidence, creates or reuses a supplier snapshot, and processes the existing parser, matcher, supplier offer, snapshot, availability, and audit pipeline.

Idempotency is content-hash based per source and snapshot type. Repeating the same preview returns the same batch; repeating confirm does not create another raw record or snapshot.

Missing condition remains unknown. The onboarding flow does not default missing condition to `NEW`; only explicit parser evidence or a future explicit supplier/source default can set a concrete condition.

## 1C Preview And Confirm

Use `/imports/onec` or call:

```bash
POST /api/v1/onboarding/1c/preview
POST /api/v1/onboarding/1c/{batch_id}/confirm
```

Preview stores a manual import batch and an auditable dry-run `OneCImportRun`. Confirm reuses the same file content and calls the existing read-only 1C import pipeline for item identity, stock, and cost. 1C remains source-of-truth only for identity, stock, and procurement cost; it does not publish listings or mutate Avito.

## Product Master Onboarding

Use `/onboarding` or call:

```bash
POST /api/v1/onboarding/products
```

The endpoint creates or reuses a `Product`, creates or reuses a `ProductVariant` by canonical key, adds safe aliases, and can link an existing 1C item manually. Unknown condition can be selected intentionally and is stored as null.

## Publication Readiness

Sprint 1.2 does not perform live Avito OAuth, publishing, updating, or external acceptance checks. A validated internal dry run is reported by:

```bash
GET /api/v1/control/listings/{listing_id}/dry-run-validation
```

The success marker is `INTERNAL_DRY_RUN_VALIDATED` only when the approved listing has title, description, price, stock decision, a dry-run success job, and the Avito contract remains disabled.
