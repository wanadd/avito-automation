from __future__ import annotations

from app.integrations.avito_contract.types import AvitoCategoryNode, AvitoFieldContract


class PublicContractProvider:
    async def get_category_tree(self) -> list[AvitoCategoryNode]:
        return []

    async def get_category_fields(self, node_slug: str) -> list[AvitoFieldContract]:
        return []


class LiveApiContractProvider:
    def __init__(self) -> None:
        self.enabled = False

    async def get_category_tree(self) -> list[AvitoCategoryNode]:
        raise RuntimeError("Live Avito API contract access is disabled until explicit credentials are configured.")

    async def get_category_fields(self, node_slug: str) -> list[AvitoFieldContract]:
        raise RuntimeError("Live Avito API contract access is disabled until explicit credentials are configured.")
