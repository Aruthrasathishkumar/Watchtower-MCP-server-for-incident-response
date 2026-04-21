"""Runbook loader and validator.

Runbooks are YAML files in the project's top-level runbooks/ directory.
They describe incident-response procedures: triggers, checks, and remedies.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml


log = logging.getLogger(__name__)


# Valid signal types a trigger can reference
VALID_SIGNALS = {
    "log_burst",
    "high_latency",
    "pod_restart",
    "service_down",
    "metric_anomaly",
}

# Valid check types
VALID_CHECK_TYPES = {"prometheus", "loki", "shell"}

# Valid remedy safety levels
VALID_SAFETY_LEVELS = {"read_only", "disruptive", "unknown"}


# Data classes 

@dataclass
class Trigger:
    signal: str
    service: Optional[str] = None
    threshold: Optional[float] = None


@dataclass
class Check:
    id: str
    description: str
    type: str
    query: str
    window: Optional[str] = None


@dataclass
class Remedy:
    id: str
    description: str
    requires_approval: bool
    command: str
    safety: str


@dataclass
class Runbook:
    id: str
    description: str
    version: int
    triggers: list[Trigger] = field(default_factory=list)
    checks: list[Check] = field(default_factory=list)
    remedies: list[Remedy] = field(default_factory=list)
    source_file: str = ""


# Validation 

class RunbookError(Exception):
    """Raised for invalid runbook YAML."""


def _require(d: dict, key: str, runbook_path: str) -> Any:
    if key not in d:
        raise RunbookError(f"{runbook_path}: missing required key '{key}'")
    return d[key]


def _parse_trigger(t: dict, path: str) -> Trigger:
    signal = _require(t, "signal", path)
    if signal not in VALID_SIGNALS:
        raise RunbookError(
            f"{path}: invalid trigger signal '{signal}'. "
            f"Valid: {sorted(VALID_SIGNALS)}"
        )
    return Trigger(
        signal=signal,
        service=t.get("service"),
        threshold=t.get("threshold"),
    )


def _parse_check(c: dict, path: str) -> Check:
    check_type = _require(c, "type", path)
    if check_type not in VALID_CHECK_TYPES:
        raise RunbookError(
            f"{path}: invalid check type '{check_type}'. "
            f"Valid: {sorted(VALID_CHECK_TYPES)}"
        )
    return Check(
        id=_require(c, "id", path),
        description=_require(c, "description", path),
        type=check_type,
        query=_require(c, "query", path),
        window=c.get("window"),
    )


def _parse_remedy(r: dict, path: str) -> Remedy:
    safety = r.get("safety", "unknown")
    if safety not in VALID_SAFETY_LEVELS:
        raise RunbookError(
            f"{path}: invalid safety level '{safety}'. "
            f"Valid: {sorted(VALID_SAFETY_LEVELS)}"
        )
    return Remedy(
        id=_require(r, "id", path),
        description=_require(r, "description", path),
        requires_approval=bool(r.get("requires_approval", True)),
        command=r.get("command", ""),
        safety=safety,
    )


def parse_runbook(data: dict, source_file: str) -> Runbook:
    """Validate and parse a runbook dict into a Runbook object."""
    rb_id = _require(data, "id", source_file)
    if not isinstance(rb_id, str) or not rb_id:
        raise RunbookError(f"{source_file}: 'id' must be a non-empty string")

    return Runbook(
        id=rb_id,
        description=_require(data, "description", source_file),
        version=int(data.get("version", 1)),
        triggers=[_parse_trigger(t, source_file) for t in data.get("triggers", [])],
        checks=[_parse_check(c, source_file) for c in data.get("checks", [])],
        remedies=[_parse_remedy(r, source_file) for r in data.get("remedies", [])],
        source_file=source_file,
    )


# Loader 

def _default_runbooks_dir() -> Path:
    """Resolve the runbooks directory relative to the project root.

    The env var WATCHTOWER_RUNBOOKS_DIR overrides this.
    """
    env = os.environ.get("WATCHTOWER_RUNBOOKS_DIR")
    if env:
        return Path(env)
    # Default: go up from server/watchtower/ to project root, then /runbooks
    return Path(__file__).resolve().parents[2] / "runbooks"


def load_runbooks(directory: Optional[Path] = None) -> list[Runbook]:
    """Load and validate all runbook YAML files in a directory."""
    directory = directory or _default_runbooks_dir()
    if not directory.exists():
        log.warning("Runbooks directory %s does not exist", directory)
        return []

    runbooks: list[Runbook] = []
    for path in sorted(directory.glob("*.yaml")):
        try:
            with open(path) as f:
                data = yaml.safe_load(f)
            if not isinstance(data, dict):
                log.warning("%s: top-level is not a mapping, skipping", path)
                continue
            runbooks.append(parse_runbook(data, source_file=str(path)))
        except (yaml.YAMLError, RunbookError) as exc:
            log.error("Failed to load %s: %s", path, exc)

    log.info("Loaded %d runbook(s) from %s", len(runbooks), directory)
    return runbooks


def runbook_by_id(runbook_id: str,
                  directory: Optional[Path] = None) -> Optional[Runbook]:
    """Find a runbook by its id."""
    for rb in load_runbooks(directory):
        if rb.id == runbook_id:
            return rb
    return None


def match_runbooks(signals: list[str], service: Optional[str] = None,
                   directory: Optional[Path] = None) -> list[Runbook]:
    """Return runbooks whose triggers match any of the given signals + service."""
    matches: list[Runbook] = []
    for rb in load_runbooks(directory):
        for trigger in rb.triggers:
            if trigger.signal not in signals:
                continue
            if trigger.service and service and trigger.service != service:
                continue
            matches.append(rb)
            break  # any trigger match = runbook applies
    return matches