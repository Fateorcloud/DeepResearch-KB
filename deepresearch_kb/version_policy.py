"""Time-aware version selection, independent of storage and semantic ranking."""

from dataclasses import dataclass
from datetime import datetime, timezone


def utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("version timestamps must be timezone-aware datetimes")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class VersionCandidate:
    document_id: str
    version: int
    effective_at: datetime
    deprecated_at: datetime | None = None
    authority: int = 0

    def __post_init__(self):
        if not isinstance(self.document_id, str) or not self.document_id.strip() or type(self.version) is not int or self.version < 1:
            raise ValueError("document identity and positive version required")
        object.__setattr__(self, "effective_at", utc(self.effective_at))
        if self.deprecated_at is not None:
            object.__setattr__(self, "deprecated_at", utc(self.deprecated_at))
            if self.deprecated_at < self.effective_at:
                raise ValueError("deprecation precedes effective date")
        if type(self.authority) is not int or not 0 <= self.authority <= 100:
            raise ValueError("authority must be an integer from 0 to 100")


@dataclass(frozen=True)
class SelectedVersion:
    candidate: VersionCandidate
    status: str
    reason: str


def select_versions(candidates, *, at: datetime, include_superseded=False,
                    include_deprecated=False) -> list[SelectedVersion]:
    """Select before retrieval: an excluded latest version never revives an old one."""
    at = utc(at)
    groups = {}
    identities = set()
    for candidate in candidates:
        key = (candidate.document_id, candidate.version)
        if key in identities:
            raise ValueError("duplicate document/version candidate")
        identities.add(key)
        if candidate.effective_at <= at:
            groups.setdefault(candidate.document_id, []).append(candidate)
    output = []
    for document_id in sorted(groups):
        versions = sorted(groups[document_id], key=lambda c: (c.effective_at, c.version), reverse=True)
        for index, candidate in enumerate(versions):
            deprecated = candidate.deprecated_at is not None and candidate.deprecated_at <= at
            if index and not include_superseded:
                continue
            if deprecated and not include_deprecated:
                continue
            status = "deprecated" if deprecated else "superseded" if index else "active"
            output.append(SelectedVersion(candidate, status,
                f"effective at {at.isoformat()}; " + ("latest eligible revision" if not index else "explicit history inclusion") +
                ("; explicit deprecated inclusion" if deprecated else "")))
    return output
