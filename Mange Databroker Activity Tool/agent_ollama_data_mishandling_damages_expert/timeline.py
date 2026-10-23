"""Store user-reported events and evidence references for impact review."""

import json
import os
import re
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Literal, TypedDict, cast
from uuid import uuid4

from react_framework import AgentTool, CaseWorkspace
from react_framework.tool_catalog import bind_tool


TimelineKind = Literal[
    "notice",
    "delivery",
    "broker_response",
    "later_observation",
    "impact_report",
    "correction",
    "other",
]
DateBasis = Literal["evidence", "user_reported", "estimated", "unknown"]

TIMELINE_KINDS: tuple[TimelineKind, ...] = (
    "notice",
    "delivery",
    "broker_response",
    "later_observation",
    "impact_report",
    "correction",
    "other",
)


DATE_BASES: tuple[DateBasis, ...] = (
    "evidence",
    "user_reported",
    "estimated",
    "unknown",
)
MAX_DESCRIPTION_LENGTH = 5_000


class EvidenceReference(TypedDict):
    path: str
    sha256: str
    description: str
    source: str
    created_received_date: str
    sender: str
    recipient: str
    event_relationship: str


class TimelineEvent(TypedDict):
    event_id: str
    event_type: TimelineKind
    event_date: str
    date_basis: DateBasis
    description: str
    evidence: list[EvidenceReference]
    corrects_event_id: str
    recorded_at: str
    source: Literal["user_reported"]


class ImpactTimeline(TypedDict):
    case_id: str
    events: list[TimelineEvent]


def load_timeline(workspace: CaseWorkspace) -> ImpactTimeline:
    """Load a validated, case-local event timeline; missing means no events."""
    path = _timeline_path(workspace)
    try:
        with path.open(encoding="utf-8") as timeline_file:
            data = json.load(timeline_file)
    except FileNotFoundError:
        return {"case_id": workspace.case_id, "events": []}
    except json.JSONDecodeError as error:
        raise ValueError(f"Impact timeline contains invalid JSON: {path.name}") from error

    if (
        not isinstance(data, dict)
        or set(data) != {"case_id", "events"}
        or data["case_id"] != workspace.case_id
        or not isinstance(data["events"], list)
    ):
        raise ValueError("Impact timeline has an invalid structure or case identifier.")
    events = [_validate_event(event) for event in data["events"]]
    event_ids = {event["event_id"] for event in events}
    if len(event_ids) != len(events):
        raise ValueError("Impact timeline contains duplicate event identifiers.")
    for event in events:
        if event["corrects_event_id"] and (
            event["corrects_event_id"] not in event_ids
            or event["corrects_event_id"] == event["event_id"]
        ):
            raise ValueError("Impact timeline correction points to an invalid event.")
    events.sort(key=_event_sort_key)
    return {"case_id": workspace.case_id, "events": events}


def add_timeline_event(
    workspace: CaseWorkspace,
    event_type: str,
    description: str,
    event_date: str = "",
    date_basis: str = "unknown",
    evidence_path: str = "",
    evidence_description: str = "",
    evidence_source: str = "",
    evidence_created_received_date: str = "",
    evidence_sender: str = "",
    evidence_recipient: str = "",
    evidence_relationship: str = "",
    corrects_event_id: str = "",
) -> TimelineEvent:
    """Append a user-reported event with an optional hash-verified evidence link."""
    if event_type not in TIMELINE_KINDS:
        raise ValueError("Choose a supported timeline event type.")
    if not isinstance(description, str) or not description.strip():
        raise ValueError("Describe the event before adding it.")
    description = description.strip()
    if len(description) > MAX_DESCRIPTION_LENGTH:
        raise ValueError(
            f"Event description must be no longer than {MAX_DESCRIPTION_LENGTH} characters."
        )
    if date_basis not in DATE_BASES:
        raise ValueError("Choose a supported date source.")
    normalized_date = event_date.strip()
    if date_basis == "unknown":
        if normalized_date:
            raise ValueError("Leave the date blank when its source is unknown.")
    else:
        _validate_date(normalized_date)

    if date_basis == "evidence" and not evidence_path:
        raise ValueError("Link an imported original when the date source is evidence.")
    if event_type == "correction":
        if not corrects_event_id:
            raise ValueError("Select the earlier event this correction refers to.")
    elif corrects_event_id:
        raise ValueError("Only a correction event can refer to an earlier event.")

    metadata = {
        "description": evidence_description.strip(),
        "source": evidence_source.strip(),
        "created_received_date": evidence_created_received_date.strip(),
        "sender": evidence_sender.strip(),
        "recipient": evidence_recipient.strip(),
        "event_relationship": evidence_relationship.strip(),
    }
    for field_name, field_value in metadata.items():
        if len(field_value) > 500:
            raise ValueError(f"Evidence {field_name.replace('_', ' ')} must be 500 characters or fewer.")
    if metadata["created_received_date"]:
        _validate_date(metadata["created_received_date"])

    evidence: list[EvidenceReference] = []
    if evidence_path:
        match = next(
            (
                item
                for item in workspace.find_files(Path(evidence_path).name, limit=100)
                if item["path"] == evidence_path
            ),
            None,
        )
        if match is None:
            raise ValueError(
                "Evidence must refer to a file already imported into this case's originals folder."
            )
        evidence.append({
            "path": match["path"],
            "sha256": match["sha256"],
            **metadata,
        })
    elif any(metadata.values()):
        raise ValueError("Evidence context requires a linked imported original.")

    timeline = load_timeline(workspace)
    event_ids = {item["event_id"] for item in timeline["events"]}
    if corrects_event_id and corrects_event_id not in event_ids:
        raise ValueError("The correction target must be an existing timeline event.")
    event: TimelineEvent = {
        "event_id": str(uuid4()),
        "event_type": cast(TimelineKind, event_type),
        "event_date": normalized_date,
        "date_basis": cast(DateBasis, date_basis),
        "description": description,
        "evidence": evidence,
        "corrects_event_id": corrects_event_id,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "source": "user_reported",
    }
    timeline["events"].append(event)
    timeline["events"].sort(key=_event_sort_key)
    _write_timeline(workspace, timeline)
    return event


def create_timeline_tools(workspace: CaseWorkspace) -> tuple[AgentTool, ...]:
    """Bind read-only timeline access for one impact-specialist case."""
    return (
        bind_tool(
            "read_impact_timeline",
            lambda _arguments: load_timeline(workspace),
        ),
    )


def build_attorney_review_draft(
    workspace: CaseWorkspace,
    counsel_questions: str = "",
) -> str:
    """Build a user-reviewable factual draft without copying evidence contents."""
    if not isinstance(counsel_questions, str):
        raise ValueError("Questions for counsel must be text.")
    if len(counsel_questions) > MAX_DESCRIPTION_LENGTH:
        raise ValueError(
            f"Questions must be no longer than {MAX_DESCRIPTION_LENGTH} characters."
        )
    timeline = load_timeline(workspace)
    evidence_files = workspace.find_files("", limit=100)
    current_hashes = {
        item["path"]: item["sha256"]
        for item in evidence_files
    }
    lines = [
        "# Attorney-review draft",
        "",
        f"Case ID: {workspace.case_id}",
        "",
        "> This is a user-prepared factual organization draft, not legal advice,",
        "> a finding that an event occurred, or a conclusion that a law was violated.",
        "> Timeline entries are user-reported. File hashes identify bytes, not",
        "> authenticity. Review every item and remove anything you do not want to share.",
        "",
        "## Chronology",
        "",
    ]
    if not timeline["events"]:
        lines.append("No timeline events have been recorded.")
        lines.append("")
    for event in timeline["events"]:
        when = event["event_date"] or "Date unknown"
        if event["date_basis"] == "estimated":
            when = f"Estimated: {when}"
        elif event["date_basis"] == "user_reported":
            when = f"User-reported date: {when}"
        lines.extend([
            f"### {when} — {event['event_type'].replace('_', ' ').title()}",
            "",
            f"- Record source: user-reported on {event['recorded_at']}",
            f"- Date basis: {event['date_basis'].replace('_', ' ')}",
            f"- User description: {_as_blockquote(event['description'])}",
        ])
        if event["corrects_event_id"]:
            lines.append(f"- Correction of event ID: `{event['corrects_event_id']}`")
        for reference in event["evidence"]:
            current_hash = current_hashes.get(reference["path"])
            if current_hash is None:
                integrity = (
                    "not present in the current index of up to 100 originals "
                    "(possibly missing)"
                )
            elif current_hash != reference["sha256"]:
                integrity = "current file hash differs from linked hash"
            else:
                integrity = "current file hash matches linked hash"
            lines.append(
                f"- Linked original: `{reference['path']}` "
                f"(SHA-256 `{reference['sha256']}`; {integrity})"
            )
            for label, key in (
                ("What it is", "description"),
                ("User-described source", "source"),
                ("Created/received date", "created_received_date"),
                ("Sender", "sender"),
                ("Recipient", "recipient"),
                ("Relation to event", "event_relationship"),
            ):
                if reference[key]:
                    lines.append(f"- {label}: {_as_blockquote(reference[key])}")
        lines.append("")

    lines.extend(["## Imported evidence index", ""])
    if not evidence_files:
        lines.append("No original evidence files are currently imported.")
    else:
        for evidence_file in evidence_files:
            lines.append(
                f"- `{evidence_file['path']}` — {evidence_file['size_bytes']} bytes; "
                f"SHA-256 `{evidence_file['sha256']}`"
            )
    lines.extend([
        "",
        "Evidence file contents are not copied into this draft. Unsupported or",
        "unreviewed files may still appear in the index; this list is not an",
        "independent assessment of their contents or authenticity. The index",
        "lists at most 100 originals.",
        "",
        "## Questions for counsel",
        "",
        _as_blockquote(counsel_questions.strip())
        if counsel_questions.strip()
        else "No questions have been added.",
        "",
        "## Scope and limitations",
        "",
        "- This draft is based on locally stored, user-entered timeline descriptions",
        "  and imported-file metadata available when it was generated.",
        "- It does not include an agent legal opinion, verified legal research, or",
        "  a damages valuation.",
        "- Applicability depends on facts and law that have not been determined here.",
        "- The jurisdiction with the strongest privacy protections is not assumed to",
        "  govern the user; any such comparison must be labeled separately.",
        "",
    ])
    return "\n".join(lines)


def _as_blockquote(value: str) -> str:
    """Render user text as quoted material, preserving line boundaries."""
    return "\n".join(f"> {line}" for line in value.splitlines()) or ">"


def _timeline_path(workspace: CaseWorkspace) -> Path:
    """Return the case-local timeline path and reject a linked file."""
    path = workspace.case_path / "impact_timeline.json"
    if path.is_symlink():
        raise ValueError("Symbolic links are not allowed for the impact timeline.")
    return path


def _write_timeline(workspace: CaseWorkspace, timeline: ImpactTimeline) -> None:
    """Atomically persist only this case's validated timeline."""
    path = _timeline_path(workspace)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=workspace.case_path,
            prefix=".impact_timeline.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            json.dump(timeline, temporary_file, indent=2)
            temporary_file.write("\n")
        if path.is_symlink():
            raise ValueError("Symbolic links are not allowed for the impact timeline.")
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def _validate_event(value: object) -> TimelineEvent:
    """Reject malformed or unexpected event data before showing it to the agent."""
    legacy_keys = {
        "event_id",
        "event_type",
        "event_date",
        "date_basis",
        "description",
        "evidence",
        "recorded_at",
        "source",
    }
    current_keys = legacy_keys | {"corrects_event_id"}
    if not isinstance(value, dict) or set(value) not in (legacy_keys, current_keys):
        raise ValueError("Impact timeline event has missing or unexpected fields.")
    is_legacy_event = set(value) == legacy_keys
    if (
        not isinstance(value["event_id"], str)
        or not value["event_id"]
        or value["event_type"] not in TIMELINE_KINDS
        or value["date_basis"] not in DATE_BASES
        or value["source"] != "user_reported"
        or not isinstance(value["event_date"], str)
        or not isinstance(value["description"], str)
        or not value["description"].strip()
        or len(value["description"]) > MAX_DESCRIPTION_LENGTH
        or not isinstance(value["recorded_at"], str)
        or not isinstance(value["evidence"], list)
    ):
        raise ValueError("Impact timeline event contains invalid values.")
    try:
        datetime.fromisoformat(value["recorded_at"])
    except ValueError as error:
        raise ValueError("Impact timeline event has an invalid recorded timestamp.") from error
    event_date = value["event_date"]
    if value["date_basis"] == "unknown":
        if event_date:
            raise ValueError("An unknown event date must be blank.")
    else:
        _validate_date(event_date)
    evidence: list[EvidenceReference] = []
    for item in value["evidence"]:
        if not isinstance(item, dict):
            raise ValueError("Impact timeline has an invalid evidence reference.")
        legacy_evidence_keys = {"path", "sha256"}
        context_keys = legacy_evidence_keys | {
            "description",
            "source",
            "created_received_date",
            "sender",
            "recipient",
            "event_relationship",
        }
        if (
            set(item) not in (legacy_evidence_keys, context_keys)
            or not isinstance(item["path"], str)
            or not _is_original_path(item["path"])
            or not isinstance(item["sha256"], str)
            or len(item["sha256"]) != 64
            or any(character not in "0123456789abcdef" for character in item["sha256"])
        ):
            raise ValueError("Impact timeline has an invalid evidence reference.")
        context = {
            key: item.get(key, "")
            for key in (
                "description",
                "source",
                "created_received_date",
                "sender",
                "recipient",
                "event_relationship",
            )
        }
        if any(not isinstance(value, str) or len(value) > 500 for value in context.values()):
            raise ValueError("Impact timeline evidence context is invalid.")
        if context["created_received_date"]:
            _validate_date(context["created_received_date"])
        evidence.append({
            "path": item["path"],
            "sha256": item["sha256"],
            **context,
        })
    corrects_event_id = value.get("corrects_event_id", "")
    if not isinstance(corrects_event_id, str):
        raise ValueError("Impact timeline correction reference is invalid.")
    if (
        value["event_type"] == "correction"
        and not corrects_event_id
        and not is_legacy_event
    ):
        raise ValueError("Impact timeline correction is missing its earlier event.")
    if value["event_type"] != "correction" and corrects_event_id:
        raise ValueError("Only a correction can refer to an earlier event.")
    return {
        "event_id": value["event_id"],
        "event_type": value["event_type"],
        "event_date": event_date,
        "date_basis": value["date_basis"],
        "description": value["description"],
        "evidence": evidence,
        "corrects_event_id": corrects_event_id,
        "recorded_at": value["recorded_at"],
        "source": "user_reported",
    }


def _event_sort_key(event: TimelineEvent) -> tuple[str, str]:
    """Sort known event dates chronologically, then undated entries."""
    return (event["event_date"] or "9999-12-31", event["recorded_at"])


def _validate_date(value: str) -> None:
    """Require a real calendar date in the visible YYYY-MM-DD format."""
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("Enter a valid date in YYYY-MM-DD format.")
    try:
        date.fromisoformat(value)
    except ValueError as error:
        raise ValueError("Enter a valid date in YYYY-MM-DD format.") from error


def _is_original_path(value: str) -> bool:
    """Accept only normalized case-relative paths inside originals/."""
    normalized = value.replace("\\", "/")
    path = PurePosixPath(normalized)
    return (
        normalized.startswith("originals/")
        and not path.is_absolute()
        and all(part not in {"", ".", ".."} for part in path.parts)
    )
