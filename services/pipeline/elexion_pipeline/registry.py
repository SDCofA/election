from __future__ import annotations

import json
from pathlib import Path

from .domain import SourceDefinition

DEFAULT_REGISTRY = Path(__file__).parent / "config" / "sources.json"


class SourceNotApprovedError(PermissionError):
    pass


class SourceRegistry:
    def __init__(self, sources: list[SourceDefinition]) -> None:
        duplicates = {
            item.id for item in sources if sum(source.id == item.id for source in sources) > 1
        }
        if duplicates:
            raise ValueError(f"Duplicate source IDs: {sorted(duplicates)}")
        self._sources = {item.id: item for item in sources}

    @classmethod
    def from_path(cls, path: Path = DEFAULT_REGISTRY) -> SourceRegistry:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return cls([SourceDefinition.model_validate(item) for item in payload["sources"]])

    def get(self, source_id: str) -> SourceDefinition:
        try:
            return self._sources[source_id]
        except KeyError as error:
            raise KeyError(f"Unknown source: {source_id}") from error

    def require_approved(self, source_id: str) -> SourceDefinition:
        source = self.get(source_id)
        if not source.approved:
            raise SourceNotApprovedError(
                f"Source {source_id} is disabled until license approval: {source.license_id}"
            )
        return source

    def approved(self) -> list[SourceDefinition]:
        return sorted(
            (source for source in self._sources.values() if source.approved),
            key=lambda source: source.id,
        )

    def blocked(self) -> list[SourceDefinition]:
        return sorted(
            (source for source in self._sources.values() if not source.approved),
            key=lambda source: source.id,
        )
