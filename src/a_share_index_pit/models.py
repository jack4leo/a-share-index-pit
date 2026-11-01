from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class IndexRef:
    """A discovered index candidate; provider is the index publisher family."""

    provider: str
    code: str
    name: str
    catalog_url: str
    source_provider: str
    note: str = ""

    @property
    def key(self) -> str:
        return f"{self.provider}:{self.code}"


@dataclass
class Snapshot:
    """One constituent state at an effective/source date."""

    index: IndexRef
    source_date: str
    members: list[dict[str, Any]]
    source_provider: str
    source_url: str
    source_sha256: str
    valid_boundary: str = "unknown"
    confidence: str = "observed_state_only"


@dataclass
class FetchResult:
    index: IndexRef
    status: str
    snapshots: list[Snapshot] = field(default_factory=list)
    source_provider: str = ""
    source_url: str = ""
    source_sha256: str = ""
    message: str = ""
