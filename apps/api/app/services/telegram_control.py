import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.enums import Marketplace, PublicationIntentType
from app.services.publication import (
    cancel_publication_job,
    control_overview,
    create_publication_intent,
    process_publication_job,
    retry_publication_job,
    review_queue,
)


def is_authorized_operator(operator_id: str) -> bool:
    return operator_id in get_settings().telegram_operator_id_set


async def handle_operator_command(session: AsyncSession, operator_id: str, text: str) -> str:
    parts = text.strip().split()
    command = parts[0].lower() if parts else "/help"
    read_only = command in {"/status", "/review", "/ready", "/blocked", "/errors", "/jobs", "/help"}
    if not read_only and not is_authorized_operator(operator_id):
        return "DENIED"
    if command == "/help":
        return "/status /review /ready /blocked /errors /jobs /dryrun <listing_id> /retry <job_id> /cancel <job_id>"
    if command == "/status":
        overview = await control_overview(session)
        return (
            f"ready={overview['generic_ready']} approved={overview['approved']} "
            f"review={overview['review_required']} no_stock={overview['not_ready']} "
            f"blocked={overview['jobs_blocked']} errors={overview['jobs_failed']}"
        )
    if command == "/ready":
        overview = await control_overview(session)
        return f"ready={overview['generic_ready']} approved={overview['approved']}"
    if command == "/blocked":
        overview = await control_overview(session)
        return f"blocked={overview['jobs_blocked']}"
    if command == "/errors":
        overview = await control_overview(session)
        return f"errors={overview['jobs_failed']} alerts={overview['open_alerts']}"
    if command == "/jobs":
        overview = await control_overview(session)
        return (
            f"queued={overview['jobs_queued']} retrying={overview['jobs_retrying']} "
            f"blocked={overview['jobs_blocked']} failed={overview['jobs_failed']} "
            f"dryrun={overview['dry_run_success']}"
        )
    if command == "/review":
        items = await review_queue(session, limit=5)
        if not items:
            return "review queue empty"
        return "\n".join(f"{item['listing_id']} {item['generic_readiness']} {item['reason']} {item['price_minor']}" for item in items)
    if command == "/dryrun" and len(parts) == 2:
        intent, job, _ = await create_publication_intent(session, uuid.UUID(parts[1]), marketplace=Marketplace.AVITO, intent_type=PublicationIntentType.CREATE, requested_by=f"telegram:{operator_id}", dry_run=True)
        processed = await process_publication_job(session, job.id)
        return f"{intent.id} {processed.status.value}"
    if command == "/retry" and len(parts) == 2:
        job = await retry_publication_job(session, uuid.UUID(parts[1]), requested_by=f"telegram:{operator_id}")
        return f"{job.id} {job.status.value}"
    if command == "/cancel" and len(parts) == 2:
        job = await cancel_publication_job(session, uuid.UUID(parts[1]), requested_by=f"telegram:{operator_id}")
        return f"{job.id} {job.status.value}"
    return "unsupported command"
