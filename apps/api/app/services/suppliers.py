import re
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog
from app.models.supplier import Supplier


def normalize_supplier_name(name: str) -> str:
    return re.sub(r"\s+", " ", name).strip()


def supplier_code_seed(name: str) -> str:
    seed = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return (seed or "supplier")[:48]


async def create_operator_supplier(
    session: AsyncSession,
    *,
    name: str,
    is_active: bool = True,
    actor_id: uuid.UUID | None = None,
) -> Supplier:
    normalized_name = normalize_supplier_name(name)
    if not normalized_name:
        raise ValueError("SUPPLIER_NAME_REQUIRED")
    if len(normalized_name) > 255:
        raise ValueError("SUPPLIER_NAME_TOO_LONG")

    duplicate = await session.scalar(select(Supplier).where(func.lower(Supplier.name) == normalized_name.lower()))
    if duplicate is not None:
        raise ValueError("SUPPLIER_NAME_EXISTS")

    code = await unique_supplier_code(session, supplier_code_seed(normalized_name))
    supplier = Supplier(code=code, name=normalized_name, is_active=is_active)
    session.add(supplier)
    await session.flush()
    session.add(
        AuditLog(
            entity_type="Supplier",
            entity_id=supplier.id,
            action="SUPPLIER_CREATED",
            old_value=None,
            new_value={"name": supplier.name, "code": supplier.code, "is_active": supplier.is_active},
            actor_type="WEB_OPERATOR",
            actor_id=str(actor_id) if actor_id is not None else None,
        )
    )
    await session.commit()
    await session.refresh(supplier)
    return supplier


async def unique_supplier_code(session: AsyncSession, seed: str) -> str:
    code = seed
    suffix = 2
    while await session.scalar(select(Supplier.id).where(Supplier.code == code)):
        tail = f"-{suffix}"
        code = f"{seed[:64 - len(tail)]}{tail}"
        suffix += 1
    return code
