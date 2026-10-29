"""Portable diagnostic records. No Blender imports belong in this module."""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class Distribution:
    name: str
    version: str
    path: str
    owner: str
    source: str  # wheel, installed, bundled
    requires: list[str] = field(default_factory=list)
    modules: list[str] = field(default_factory=list)
    native_files: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)


@dataclass
class Addon:
    id: str
    name: str
    path: str
    version: str = ""
    module: str = ""
    enabled: bool | None = None
    kind: str = "extension"
    wheels: list[str] = field(default_factory=list)


@dataclass
class Finding:
    code: str
    severity: str  # error, warning, info
    title: str
    summary: str
    owners: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    advice: str = ""
    confidence: str = "observed"  # observed, potential
    packages: list[str] = field(default_factory=list)


@dataclass
class ScanResult:
    roots: list[str]
    addons: list[Addon] = field(default_factory=list)
    distributions: list[Distribution] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    loaded: dict[str, str] = field(default_factory=dict)
    environment: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    schema_version: int = 1

    def to_dict(self) -> dict:
        return asdict(self)

