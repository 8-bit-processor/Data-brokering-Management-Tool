"""Persist metadata-only opt-out case progress and evidence fingerprints."""

import hashlib
import json
import os
import re
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Literal, TypeGuard, TypedDict, cast
from uuid import uuid4

from ollama_databroker_compliance_agent.directory import (
    BROKER_DIRECTORY,
    BrokerRecord,
)


CaseStatus = Literal[
    "prepared",
    "in_progress",
    "awaiting_user_verification",
    "submission_initiated",
    "acknowledged",
    "response_received",
    "user_reports_removed",
    "user_reports_not_removed",
]

EvidenceKind = Literal[
    "submission_receipt",
    "broker_acknowledgment",
    "broker_response",
    "removal_check",
    "other",
]

CASE_STATUSES: tuple[CaseStatus, ...] = (
    "prepared",
    "in_progress",
    "awaiting_user_verification",
    "submission_initiated",
    "acknowledged",
    "response_received",
    "user_reports_removed",
    "user_reports_not_removed",
)
EVIDENCE_KINDS: tuple[EvidenceKind, ...] = (
    "submission_receipt",
    "broker_acknowledgment",
    "broker_response",
    "removal_check",
    "other",
)


def is_case_status(value: str) -> TypeGuard[CaseStatus]:
    """Return whether text names one of the supported case statuses."""
    return value in CASE_STATUSES


def is_evidence_kind(value: str) -> TypeGuard[EvidenceKind]:
    """Return whether text names one of the supported evidence categories."""
    return value in EVIDENCE_KINDS


class CaseEvent(TypedDict):
    """One timestamped status or evidence-fingerprint event."""

    event_id: str
    kind: Literal["status", "evidence"]
    status: str
    evidence_kind: str
    sha256: str
    recorded_at: str


class OptOutCase(TypedDict):
    """A case record that deliberately excludes user identifiers."""

    case_id: str
    broker_id: str
    broker: str
    created_at: str
    updated_at: str
    status: CaseStatus
    follow_up_date: str
    events: list[CaseEvent]


def default_case_file() -> Path:
    """Return the local application-data path for opt-out case metadata."""
    local_app_data = os.getenv("LOCALAPPDATA")
    if local_app_data:
        data_root = Path(local_app_data)
    else:
        data_root = Path(os.getenv("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return data_root / "Ollama Internet Databroker Police Agent" / "opt_out_cases.json"


def load_cases(path: Path | None = None) -> list[OptOutCase]:
    """Load and validate locally stored case metadata."""
    store_path = path or default_case_file()
    try:
        with store_path.open(encoding="utf-8") as store_file:
            records = json.load(store_file)
    except FileNotFoundError:
        return []
    except json.JSONDecodeError as error:
        raise ValueError(f"Opt-out case file contains invalid JSON: {store_path}") from error
    if not isinstance(records, list):
        raise ValueError("Opt-out case file must contain a JSON array.")
    valid_records = [
        _parse_case(record)
        for record in cast(list[object], records)
    ]
    if len({record["case_id"] for record in valid_records}) != len(valid_records):
        raise ValueError("Opt-out case file contains duplicate case identifiers.")
    return valid_records


def create_case(broker_id: str, path: Path | None = None) -> OptOutCase:
    """Create a case containing only a directory broker and generated ID."""
    broker = _find_broker(broker_id)
    now = _now()
    record: OptOutCase = {
        "case_id": str(uuid4()),
        "broker_id": broker["broker_id"],
        "broker": broker["broker"],
        "created_at": now,
        "updated_at": now,
        "status": "prepared",
        "follow_up_date": "",
        "events": [],
    }
    record["events"].append(_status_event("prepared", now))
    store_path = path or default_case_file()
    records = load_cases(store_path)
    records.append(record)
    _write_cases(store_path, records)
    return record


def update_case_status(
    case_id: str,
    status: CaseStatus,
    path: Path | None = None,
) -> OptOutCase:
    """Record a user- or workflow-reported case status transition."""
    if not is_case_status(status):
        raise ValueError("Choose a supported opt-out case status.")
    store_path = path or default_case_file()
    records = load_cases(store_path)
    record = _get_case(records, case_id)
    if record["status"] == status:
        raise ValueError("The case already has that status.")
    now = _now()
    record["status"] = status
    record["updated_at"] = now
    record["events"].append(_status_event(status, now))
    _write_cases(store_path, records)
    return record


def add_case_evidence(
    case_id: str,
    evidence_kind: EvidenceKind,
    evidence_file: Path,
    path: Path | None = None,
) -> OptOutCase:
    """Hash a selected local evidence file without saving its contents or path."""
    if not is_evidence_kind(evidence_kind):
        raise ValueError("Choose a supported evidence category.")
    if not evidence_file.is_file():
        raise ValueError("Choose an existing evidence file.")
    digest = hashlib.sha256()
    with evidence_file.open("rb") as source:
        for chunk in iter(lambda: source.read(64 * 1024), b""):
            digest.update(chunk)

    store_path = path or default_case_file()
    records = load_cases(store_path)
    record = _get_case(records, case_id)
    now = _now()
    record["updated_at"] = now
    record["events"].append(
        {
            "event_id": str(uuid4()),
            "kind": "evidence",
            "status": record["status"],
            "evidence_kind": evidence_kind,
            "sha256": digest.hexdigest(),
            "recorded_at": now,
        }
    )
    _write_cases(store_path, records)
    return record


def set_follow_up_date(
    case_id: str,
    follow_up_date: str,
    path: Path | None = None,
) -> OptOutCase:
    """Set or clear a local follow-up reminder date in YYYY-MM-DD format."""
    normalized_date = follow_up_date.strip()
    if normalized_date:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", normalized_date):
            raise ValueError("Follow-up date must use YYYY-MM-DD format.")
        try:
            date.fromisoformat(normalized_date)
        except ValueError as error:
            raise ValueError("Follow-up date must use YYYY-MM-DD format.") from error
    store_path = path or default_case_file()
    records = load_cases(store_path)
    record = _get_case(records, case_id)
    record["follow_up_date"] = normalized_date
    record["updated_at"] = _now()
    _write_cases(store_path, records)
    return record


def delete_case(case_id: str, path: Path | None = None) -> None:
    """Delete one local case and its metadata."""
    store_path = path or default_case_file()
    records = load_cases(store_path)
    remaining = [record for record in records if record["case_id"] != case_id]
    if len(remaining) == len(records):
        raise ValueError("No opt-out case has that identifier.")
    _write_cases(store_path, remaining)


def _find_broker(broker_id: str) -> BrokerRecord:
    broker = next(
        (item for item in BROKER_DIRECTORY if item["broker_id"] == broker_id),
        None,
    )
    if broker is None:
        raise ValueError("Choose a broker from the maintained directory.")
    return broker


def _get_case(records: list[OptOutCase], case_id: str) -> OptOutCase:
    record = next((item for item in records if item["case_id"] == case_id), None)
    if record is None:
        raise ValueError("No opt-out case has that identifier.")
    return record


def _status_event(status: CaseStatus, recorded_at: str) -> CaseEvent:
    return {
        "event_id": str(uuid4()),
        "kind": "status",
        "status": status,
        "evidence_kind": "",
        "sha256": "",
        "recorded_at": recorded_at,
    }


def _parse_case(record: object) -> OptOutCase:
    if not isinstance(record, dict):
        raise ValueError("Opt-out case must be a JSON object.")
    raw_mapping = cast(dict[object, object], record)
    data: dict[str, object] = {}
    for key in raw_mapping:
        if not isinstance(key, str):
            raise ValueError("Opt-out case keys must be text.")
        data[key] = raw_mapping[key]
    legacy_fields = {
        "case_id", "broker_id", "broker", "created_at", "updated_at", "status", "events"
    }
    current_fields = legacy_fields | {"follow_up_date"}
    keys = set(data)
    if keys not in (legacy_fields, current_fields):
        raise ValueError("Opt-out case has missing or unexpected fields.")
    case_id = data.get("case_id")
    broker_id = data.get("broker_id")
    broker_name = data.get("broker")
    created_at = data.get("created_at")
    updated_at = data.get("updated_at")
    status = data.get("status")
    follow_up_date = data.get("follow_up_date", "")
    raw_events = data.get("events")
    if (
        not isinstance(case_id, str)
        or not isinstance(broker_id, str)
        or not isinstance(broker_name, str)
        or not isinstance(created_at, str)
        or not isinstance(updated_at, str)
        or not isinstance(status, str)
        or not isinstance(follow_up_date, str)
    ):
        raise ValueError("Opt-out case fields must have valid text values.")
    if not isinstance(raw_events, list):
        raise ValueError("Opt-out case events must be an array.")
    if follow_up_date:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", follow_up_date):
            raise ValueError("Opt-out case has an invalid follow-up date.")
        try:
            date.fromisoformat(follow_up_date)
        except ValueError as error:
            raise ValueError("Opt-out case has an invalid follow-up date.") from error
    broker = _find_broker(broker_id)
    if broker_name != broker["broker"]:
        raise ValueError("Opt-out case broker does not match the maintained directory.")
    if not is_case_status(status):
        raise ValueError("Opt-out case has an unsupported status.")
    events: list[CaseEvent] = []
    for event in cast(list[object], raw_events):
        events.append(_parse_event(event))
    return {
        "case_id": case_id,
        "broker_id": broker_id,
        "broker": broker_name,
        "created_at": created_at,
        "updated_at": updated_at,
        "status": status,
        "follow_up_date": follow_up_date,
        "events": events,
    }


def _parse_event(event: object) -> CaseEvent:
    event_fields = {
        "event_id", "kind", "status", "evidence_kind", "sha256", "recorded_at"
    }
    if not isinstance(event, dict):
        raise ValueError("Opt-out case contains an invalid event.")
    raw_mapping = cast(dict[object, object], event)
    data: dict[str, object] = {}
    for key in raw_mapping:
        if not isinstance(key, str):
            raise ValueError("Opt-out case event keys must be text.")
        data[key] = raw_mapping[key]
    if set(data) != event_fields:
        raise ValueError("Opt-out case contains an invalid event.")
    event_id = data.get("event_id")
    kind = data.get("kind")
    status = data.get("status")
    evidence_kind = data.get("evidence_kind")
    sha256 = data.get("sha256")
    recorded_at = data.get("recorded_at")
    if (
        not isinstance(event_id, str)
        or not isinstance(kind, str)
        or not isinstance(status, str)
        or not isinstance(evidence_kind, str)
        or not isinstance(sha256, str)
        or not isinstance(recorded_at, str)
    ):
        raise ValueError("Opt-out case event fields must be text.")
    if not is_case_status(status):
        raise ValueError("Opt-out case event has an unsupported status.")
    if kind == "status":
        if evidence_kind or sha256:
            raise ValueError("Status events cannot contain evidence fields.")
    elif kind == "evidence":
        if (
            not is_evidence_kind(evidence_kind)
            or len(sha256) != 64
            or not all(character in "0123456789abcdef" for character in sha256)
        ):
            raise ValueError("Opt-out case evidence fingerprint is invalid.")
    else:
        raise ValueError("Opt-out case event kind is invalid.")
    return {
        "event_id": event_id,
        "kind": kind,
        "status": status,
        "evidence_kind": evidence_kind,
        "sha256": sha256,
        "recorded_at": recorded_at,
    }


def _write_cases(path: Path, records: list[OptOutCase]) -> None:
    """Atomically replace the case metadata JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            json.dump(records, temporary_file, indent=2)
            temporary_file.write("\n")
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
