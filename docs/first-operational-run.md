# First Operational Run

1. Start services and migrate:

```bash
docker compose up -d --build
docker compose exec -T api alembic upgrade head
```

2. Create an operator if needed:

```bash
docker compose exec -T api python -m app.cli create-operator admin --role ADMIN
```

3. Open the operator UI and sign in. Use `/imports/telegram` for supplier price text and `/imports/onec` for 1C stock/cost exports.

4. For Telegram, choose the source, paste the price list, preview, inspect line counts and parse flags, then confirm. Confirm writes raw evidence and processes the existing snapshot pipeline.

5. For 1C, paste JSON or CSV export content, preview the dry-run match/update counts, then confirm. Confirm applies stock and cost only for matched items and keeps unmatched items in reviewable state.

6. Use `/onboarding` to create missing product master records, aliases, and manual 1C links.

7. Complete content facts, content approval, image set approval, pricing, and listing approval through the existing content, pricing, and publication pages.

8. Run an internal dry run from the publication page and check:

```bash
GET /api/v1/control/listings/{listing_id}/dry-run-validation
python -m app.cli pilot-readiness
```

Expected final internal marker for a ready pilot listing is `INTERNAL_DRY_RUN_VALIDATED`. This is not Avito external acceptance and must not be treated as live publication.
