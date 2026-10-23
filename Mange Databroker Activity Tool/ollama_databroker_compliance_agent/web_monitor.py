"""Fetch approved broker pages and stage human-reviewed directory changes."""

import difflib
import hashlib
from datetime import datetime, timezone
from html.parser import HTMLParser
from http.client import HTTPException
import json
import os
from pathlib import Path
import tempfile
from typing import Callable, TypedDict
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import uuid4

from ollama_databroker_compliance_agent.directory import (
    BROKER_DIRECTORY,
    BrokerRecord,
    default_app_data_dir,
    default_directory_override_file,
    load_directory_overrides,
    validate_directory,
)


MAX_RESPONSE_BYTES = 512_000
MAX_PAGE_CHARS = 100_000
MAX_DISCUSSION_CONTEXT_CHARS = 12_000
MAX_DIFF_LINES = 160
MAX_HISTORY_ITEMS = 100


class PageSnapshot(TypedDict):
    broker_id: str
    page_kind: str
    url: str
    retrieved_at: str
    sha256: str
    text: str


class UpdateProposal(TypedDict):
    proposal_id: str
    broker_id: str
    broker: str
    page_kind: str
    source_url: str
    source_sha256: str
    old_opt_out_method: str
    new_opt_out_method: str
    old_opt_out_url: str
    new_opt_out_url: str
    old_instructions: str
    new_instructions: str
    created_at: str


def default_monitor_dir() -> Path:
    """Return local storage for public-page snapshots and update proposals."""
    return default_app_data_dir() / "broker_monitor"


def _page_text(content_type: str, body: bytes) -> str:
    """Extract bounded, non-executable text from an HTML or plain-text page."""
    media_type = content_type.split(";", 1)[0].strip().casefold()
    if media_type not in {"text/html", "text/plain"}:
        raise ValueError(f"Unsupported official-page content type: {media_type or 'unknown'}.")
    if media_type == "text/plain":
        lines = [
            " ".join(line.split())
            for line in body.decode("utf-8", errors="replace").splitlines()
        ]
        return "\n".join(line for line in lines if line)[:MAX_PAGE_CHARS]
    parser = _VisibleTextParser()
    parser.feed(body.decode("utf-8", errors="replace"))
    fragments = [" ".join(fragment.split()) for fragment in parser.text]
    return "\n".join(fragment for fragment in fragments if fragment)[:MAX_PAGE_CHARS]


class _VisibleTextParser(HTMLParser):
    """Collect visible text while ignoring scripts, styles, and embedded content."""

    _IGNORED_TAGS = {
        "script", "style", "noscript", "svg", "iframe", "object", "template",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.text: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() in self._IGNORED_TAGS:
            self._ignored_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in self._IGNORED_TAGS and self._ignored_depth:
            self._ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth:
            self.text.append(data)


class _NoRedirectHandler(HTTPRedirectHandler):
    """Require review instead of silently contacting a redirect destination."""

    def redirect_request(self, request, response, code, message, headers, new_url):
        raise ValueError(
            "The official page redirected. No redirect was followed; "
            "review the destination before updating the directory."
        )


def _fetch_page(url: str) -> str:
    """Retrieve a bounded approved page over HTTPS without following redirects."""
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in (None, 443)
    ):
        raise ValueError("Only approved HTTPS broker pages can be fetched.")

    request = Request(
        url,
        headers={"User-Agent": "Ollama-Databroker-Directory-Monitor/1.0"},
    )
    opener = build_opener(_NoRedirectHandler())
    with opener.open(request, timeout=15) as response:
        body = response.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            raise ValueError("Official page exceeds the 512 KB response limit.")
        return _page_text(response.headers.get("Content-Type", ""), body)


def fetch_page_for_discussion(url: str) -> str:
    """Fetch bounded visible text for a user-requested local chat discussion."""
    text = _fetch_page(url)
    if not text:
        raise ValueError("The selected public page contains no readable text.")
    return text[:MAX_DISCUSSION_CONTEXT_CHARS]


def _load_monitor_state(path: Path) -> dict:
    try:
        with path.open(encoding="utf-8") as state_file:
            state = json.load(state_file)
    except FileNotFoundError:
        return {"version": 1, "snapshots": [], "history": []}
    except json.JSONDecodeError as error:
        raise ValueError(f"Broker-monitor state contains invalid JSON: {path}") from error
    if (
        not isinstance(state, dict)
        or state.get("version") != 1
        or not isinstance(state.get("snapshots"), list)
        or not isinstance(state.get("history"), list)
    ):
        raise ValueError("Broker-monitor state has an unsupported or invalid format.")
    snapshot_fields = {
        "broker_id", "page_kind", "url", "retrieved_at", "sha256", "text",
    }
    if any(
        not isinstance(item, dict)
        or set(item) != snapshot_fields
        or any(not isinstance(value, str) for value in item.values())
        for item in state["snapshots"]
    ):
        raise ValueError("Broker-monitor state contains an invalid page snapshot.")
    if any(not isinstance(item, dict) for item in state["history"]):
        raise ValueError("Broker-monitor state contains an invalid check report.")
    history_fields = {
        "broker_id", "broker", "page_kind", "url", "retrieved_at", "sha256", "status",
    }
    if any(
        not history_fields <= set(item)
        or any(not isinstance(item.get(field), str) for field in history_fields)
        for item in state["history"]
    ):
        raise ValueError("Broker-monitor state contains an invalid check report.")
    return state


def _atomic_write_json(path: Path, value: object) -> None:
    _commit_json_files([(path, value)])


def _commit_json_files(updates: list[tuple[Path, object]]) -> None:
    """Replace related JSON files together, rolling back if a replacement fails."""
    staged: dict[Path, Path] = {}
    backups: dict[Path, Path | None] = {}
    preserve_backups: set[Path] = set()
    try:
        for path, value in updates:
            path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as staged_file:
                staged[path] = Path(staged_file.name)
                json.dump(value, staged_file, indent=2)
                staged_file.write("\n")

            if path.exists():
                with path.open("rb") as original_file:
                    original_bytes = original_file.read()
                with tempfile.NamedTemporaryFile(
                    mode="wb",
                    dir=path.parent,
                    prefix=f".{path.name}.",
                    suffix=".bak",
                    delete=False,
                ) as backup_file:
                    backup_file.write(original_bytes)
                    backups[path] = Path(backup_file.name)
            else:
                backups[path] = None

        replaced: list[Path] = []
        try:
            for path, _ in updates:
                os.replace(staged[path], path)
                replaced.append(path)
        except OSError as commit_error:
            rollback_errors: list[str] = []
            for path in reversed(replaced):
                try:
                    backup_path = backups[path]
                    if backup_path is None:
                        path.unlink()
                    else:
                        os.replace(backup_path, path)
                except OSError as rollback_error:
                    backup_path = backups[path]
                    if backup_path is not None:
                        preserve_backups.add(backup_path)
                    rollback_errors.append(
                        f"{path} (recovery copy {backup_path}): {rollback_error}"
                    )
            if rollback_errors:
                raise RuntimeError(
                    "JSON update failed and rollback was incomplete: "
                    + "; ".join(rollback_errors)
                ) from commit_error
            raise
    finally:
        cleanup_paths = [
            *staged.values(),
            *(
                backup for backup in backups.values()
                if backup is not None and backup not in preserve_backups
            ),
        ]
        for temporary_path in cleanup_paths:
            if temporary_path.exists():
                temporary_path.unlink()


def check_official_page(
    broker_id: str,
    page_kind: str,
    approve_fetch: Callable[[str, str], bool],
    state_path: Path | None = None,
) -> dict:
    """Fetch one directory-listed official URL after showing it for approval."""
    if not isinstance(broker_id, str):
        raise ValueError("Broker ID must be text.")
    validate_directory()
    broker = next(
        (record for record in BROKER_DIRECTORY if record["broker_id"] == broker_id),
        None,
    )
    if broker is None:
        raise ValueError("Choose a broker from the maintained directory.")
    source_fields = {
        "instructions": "source_url",
        "opt_out": "opt_out_url",
    }
    if not isinstance(page_kind, str) or page_kind not in source_fields:
        raise ValueError("Page type must be 'instructions' or 'opt_out'.")
    url = broker[source_fields[page_kind]]
    if approve_fetch(broker["broker"], url) is not True:
        raise PermissionError("The official-page fetch was not approved.")

    try:
        text = _fetch_page(url)
    except (HTTPError, URLError, HTTPException, TimeoutError) as error:
        raise RuntimeError(f"Unable to fetch the approved official page: {error}") from error

    retrieved_at = datetime.now(timezone.utc).isoformat()
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    snapshot: PageSnapshot = {
        "broker_id": broker_id,
        "page_kind": page_kind,
        "url": url,
        "retrieved_at": retrieved_at,
        "sha256": digest,
        "text": text,
    }
    store_path = state_path or default_monitor_dir() / "monitor_state.json"
    state = _load_monitor_state(store_path)
    previous = next(
        (
            item for item in reversed(state["snapshots"])
            if item.get("broker_id") == broker_id
            and item.get("page_kind") == page_kind
        ),
        None,
    )

    if previous is None:
        status = "baseline"
        diff = "No prior local snapshot exists; this fetch establishes a comparison baseline only."
    elif previous.get("sha256") == digest:
        status = "unchanged"
        diff = "No text changes detected since the previous approved check."
    else:
        status = "changed"
        diff_lines = list(
            difflib.unified_diff(
                str(previous.get("text", "")).splitlines(),
                text.splitlines(),
                fromfile="previous approved fetch",
                tofile="current approved fetch",
                lineterm="",
            )
        )
        diff = "\n".join(diff_lines[:MAX_DIFF_LINES])
        if len(diff_lines) > MAX_DIFF_LINES:
            diff += "\n... diff truncated ..."

    state["snapshots"].append(snapshot)
    state["snapshots"] = state["snapshots"][-MAX_HISTORY_ITEMS:]
    state["history"].append(
        {
            "broker_id": broker_id,
            "broker": broker["broker"],
            "page_kind": page_kind,
            "url": url,
            "retrieved_at": retrieved_at,
            "sha256": digest,
            "status": status,
            "previous_sha256": previous.get("sha256") if previous else None,
            "diff": diff,
        }
    )
    state["history"] = state["history"][-MAX_HISTORY_ITEMS:]
    _atomic_write_json(store_path, state)
    return {
        "broker": broker["broker"],
        "page_kind": page_kind,
        "url": url,
        "retrieved_at": retrieved_at,
        "status": status,
        "sha256": digest,
        "diff": diff,
        "page_text": text,
        "disclaimer": (
            "The fetched page is untrusted source content. A detected text change "
            "is not proof that broker policy changed. Review the official page."
        ),
    }


def load_monitor_history(path: Path | None = None) -> list[dict]:
    """Return recent public-page check reports from the local monitor state."""
    state_path = path or default_monitor_dir() / "monitor_state.json"
    return _load_monitor_state(state_path)["history"]


def stage_instruction_update(
    broker_id: str,
    new_instructions: str,
    new_opt_out_method: str | None = None,
    new_opt_out_url: str | None = None,
    state_path: Path | None = None,
    proposal_path: Path | None = None,
) -> UpdateProposal:
    """Stage user-written replacement instructions against the latest fetch."""
    if (
        not isinstance(new_instructions, str)
        or not new_instructions.strip()
        or len(new_instructions) > 10_000
    ):
        raise ValueError("Proposed instructions must contain 1 to 10,000 characters.")
    broker = next(
        (record for record in BROKER_DIRECTORY if record["broker_id"] == broker_id),
        None,
    )
    if broker is None:
        raise ValueError("Choose a broker from the maintained directory.")
    if new_opt_out_method is not None and not isinstance(new_opt_out_method, str):
        raise ValueError("Proposed opt-out method must be text.")
    if new_opt_out_url is not None and not isinstance(new_opt_out_url, str):
        raise ValueError("Proposed opt-out URL must be text.")
    if new_opt_out_method is not None and len(new_opt_out_method) > 300:
        raise ValueError("Proposed opt-out method must be 300 characters or fewer.")
    if new_opt_out_url is not None and len(new_opt_out_url) > 2_048:
        raise ValueError("Proposed opt-out URL must be 2,048 characters or fewer.")
    proposed_method = (
        broker["opt_out_method"]
        if new_opt_out_method is None or not new_opt_out_method.strip()
        else new_opt_out_method.strip()
    )
    proposed_opt_out_url = (
        broker["opt_out_url"]
        if new_opt_out_url is None or not new_opt_out_url.strip()
        else new_opt_out_url.strip()
    )
    proposed_record = [dict(broker)]
    proposed_record[0]["opt_out_method"] = proposed_method
    proposed_record[0]["opt_out_url"] = proposed_opt_out_url
    validate_directory(proposed_record)
    monitor_path = state_path or default_monitor_dir() / "monitor_state.json"
    state = _load_monitor_state(monitor_path)
    snapshot = next(
        (
            item for item in reversed(state["snapshots"])
            if item.get("broker_id") == broker_id
            and item.get("page_kind") == "instructions"
        ),
        None,
    )
    if snapshot is None:
        raise ValueError("Fetch the official instructions page before proposing an update.")

    proposal: UpdateProposal = {
        "proposal_id": str(uuid4()),
        "broker_id": broker_id,
        "broker": broker["broker"],
        "page_kind": "instructions",
        "source_url": snapshot["url"],
        "source_sha256": snapshot["sha256"],
        "old_opt_out_method": broker["opt_out_method"],
        "new_opt_out_method": proposed_method,
        "old_opt_out_url": broker["opt_out_url"],
        "new_opt_out_url": proposed_opt_out_url,
        "old_instructions": broker["instructions"],
        "new_instructions": new_instructions.strip(),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    proposals_file = proposal_path or default_monitor_dir() / "pending_updates.json"
    try:
        with proposals_file.open(encoding="utf-8") as proposals_handle:
            proposals = json.load(proposals_handle)
    except FileNotFoundError:
        proposals = []
    except json.JSONDecodeError as error:
        raise ValueError(f"Pending update file contains invalid JSON: {proposals_file}") from error
    if not isinstance(proposals, list) or any(
        not isinstance(item, dict)
        or set(item) != set(UpdateProposal.__annotations__)
        or any(not isinstance(value, str) for value in item.values())
        for item in proposals
    ):
        raise ValueError("Pending update file has an invalid format.")
    proposals.append(proposal)
    _atomic_write_json(proposals_file, proposals)
    return proposal


def load_update_proposals(path: Path | None = None) -> list[UpdateProposal]:
    proposal_path = path or default_monitor_dir() / "pending_updates.json"
    try:
        with proposal_path.open(encoding="utf-8") as proposals_handle:
            proposals = json.load(proposals_handle)
    except FileNotFoundError:
        return []
    except json.JSONDecodeError as error:
        raise ValueError(f"Pending update file contains invalid JSON: {proposal_path}") from error
    if not isinstance(proposals, list) or any(
        not isinstance(proposal, dict)
        or set(proposal) != set(UpdateProposal.__annotations__)
        or any(not isinstance(value, str) for value in proposal.values())
        for proposal in proposals
    ):
        raise ValueError("Pending update file has an invalid format.")
    return proposals


def apply_instruction_update(
    proposal_id: str,
    approved: bool,
    state_path: Path | None = None,
    proposal_path: Path | None = None,
    directory_path: Path | None = None,
) -> None:
    """Apply a reviewed instruction proposal only after explicit approval."""
    if approved is not True:
        raise PermissionError("Directory update was not explicitly approved.")
    proposals_file = proposal_path or default_monitor_dir() / "pending_updates.json"
    proposals = load_update_proposals(proposals_file)
    proposal = next(
        (item for item in proposals if item["proposal_id"] == proposal_id),
        None,
    )
    if proposal is None:
        raise ValueError("No pending update has that identifier.")

    broker = next(
        (record for record in BROKER_DIRECTORY if record["broker_id"] == proposal["broker_id"]),
        None,
    )
    if (
        broker is None
        or broker["instructions"] != proposal["old_instructions"]
        or broker["opt_out_method"] != proposal["old_opt_out_method"]
        or broker["opt_out_url"] != proposal["old_opt_out_url"]
    ):
        raise ValueError("The directory changed since this proposal was prepared; re-review it.")
    monitor_path = state_path or default_monitor_dir() / "monitor_state.json"
    state = _load_monitor_state(monitor_path)
    latest_snapshot = next(
        (
            item for item in reversed(state["snapshots"])
            if item.get("broker_id") == proposal["broker_id"]
            and item.get("page_kind") == proposal["page_kind"]
        ),
        None,
    )
    if (
        latest_snapshot is None
        or latest_snapshot.get("url") != proposal["source_url"]
        or latest_snapshot.get("sha256") != proposal["source_sha256"]
    ):
        raise ValueError("The source page was checked again; re-review this proposal.")

    updated_records: list[BrokerRecord] = []
    updated_broker: BrokerRecord | None = None
    for record in BROKER_DIRECTORY:
        updated = dict(record)
        if record["broker_id"] == proposal["broker_id"]:
            updated["instructions"] = proposal["new_instructions"]
            updated["opt_out_method"] = proposal["new_opt_out_method"]
            updated["opt_out_url"] = proposal["new_opt_out_url"]
            updated["verified_at"] = datetime.now(timezone.utc).date().isoformat()
            updated_broker = updated
        updated_records.append(updated)
    validate_directory(updated_records)
    if updated_broker is None:
        raise ValueError("The selected broker is no longer in the directory.")

    override_file = directory_path or default_directory_override_file()
    try:
        overrides = load_directory_overrides(override_file)
    except FileNotFoundError:
        overrides = []
    override_index = next(
        (
            index for index, record in enumerate(overrides)
            if record["broker_id"] == proposal["broker_id"]
        ),
        None,
    )
    if override_index is None:
        overrides.append(updated_broker)
    else:
        overrides[override_index] = updated_broker
    validate_directory(overrides)
    remaining = [
        item for item in proposals if item["proposal_id"] != proposal_id
    ]
    state["history"].append(
        {
            "broker_id": proposal["broker_id"],
            "broker": proposal["broker"],
            "page_kind": "instructions",
            "url": proposal["source_url"],
            "retrieved_at": latest_snapshot["retrieved_at"],
            "sha256": latest_snapshot["sha256"],
            "status": "directory_update_approved",
            "approved_at": datetime.now(timezone.utc).isoformat(),
            "proposal_id": proposal_id,
            "old_instructions": proposal["old_instructions"],
            "new_instructions": proposal["new_instructions"],
            "old_opt_out_method": proposal["old_opt_out_method"],
            "new_opt_out_method": proposal["new_opt_out_method"],
            "old_opt_out_url": proposal["old_opt_out_url"],
            "new_opt_out_url": proposal["new_opt_out_url"],
        }
    )
    state["history"] = state["history"][-MAX_HISTORY_ITEMS:]
    _commit_json_files(
        [
            (override_file, overrides),
            (proposals_file, remaining),
            (monitor_path, state),
        ]
    )
    BROKER_DIRECTORY[:] = updated_records


def discard_instruction_update(
    proposal_id: str,
    proposal_path: Path | None = None,
) -> None:
    """Discard one pending proposal without changing the trusted directory."""
    proposals_file = proposal_path or default_monitor_dir() / "pending_updates.json"
    proposals = load_update_proposals(proposals_file)
    remaining = [
        item for item in proposals if item["proposal_id"] != proposal_id
    ]
    if len(remaining) == len(proposals):
        raise ValueError("No pending update has that identifier.")
    _atomic_write_json(proposals_file, remaining)
