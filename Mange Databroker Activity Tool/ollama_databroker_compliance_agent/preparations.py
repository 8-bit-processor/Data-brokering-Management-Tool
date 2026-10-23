"""Store local, non-identifying opt-out preparation checklists."""

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict
from uuid import uuid4

from ollama_databroker_compliance_agent.directory import (
    BROKER_DIRECTORY,
    validate_directory,
)


class Preparation(TypedDict):
    """Snapshot of the public instructions a user chose to prepare."""

    preparation_id: str
    broker_id: str
    broker: str
    saved_at: str
    verified_at: str
    opt_out_method: str
    opt_out_url: str
    source_url: str
    instructions: str


PREPARATION_FIELDS = set(Preparation.__annotations__)


def default_preparation_file() -> Path:
    """Return the local application-data file used for saved checklists."""
    local_app_data = os.getenv("LOCALAPPDATA")
    if local_app_data:
        data_root = Path(local_app_data)
    else:
        data_root = Path(os.getenv("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return (
        data_root
        / "Ollama Internet Databroker Police Agent"
        / "opt_out_preparations.json"
    )


def load_preparations(path: Path | None = None) -> list[Preparation]:
    """Read saved checklists, returning an empty list when none exist yet."""
    store_path = path or default_preparation_file()
    try:
        with store_path.open(encoding="utf-8") as store_file:
            records = json.load(store_file)
    except FileNotFoundError:
        return []
    except json.JSONDecodeError as error:
        raise ValueError(f"Saved checklist file contains invalid JSON: {store_path}") from error

    if not isinstance(records, list):
        raise ValueError("Saved checklist file must contain a JSON array.")
    for record in records:
        if not isinstance(record, dict) or set(record) != PREPARATION_FIELDS:
            raise ValueError("Saved checklist has missing or unexpected fields.")
        if any(not isinstance(value, str) for value in record.values()):
            raise ValueError("Saved checklist fields must all be text.")
    return records


def save_preparation(
    broker_id: str,
    path: Path | None = None,
) -> Preparation:
    """Save a checklist snapshot for one broker without collecting user data."""
    validate_directory()
    broker_record = next(
        (record for record in BROKER_DIRECTORY if record["broker_id"] == broker_id),
        None,
    )
    if broker_record is None:
        raise ValueError("Choose a broker from the vetted directory.")

    saved: Preparation = {
        "preparation_id": str(uuid4()),
        "broker_id": broker_record["broker_id"],
        "broker": broker_record["broker"],
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "verified_at": broker_record["verified_at"],
        "opt_out_method": broker_record["opt_out_method"],
        "opt_out_url": broker_record["opt_out_url"],
        "source_url": broker_record["source_url"],
        "instructions": broker_record["instructions"],
    }
    store_path = path or default_preparation_file()
    records = load_preparations(store_path)
    records.append(saved)
    _write_preparations(store_path, records)
    return saved


def delete_preparation(preparation_id: str, path: Path | None = None) -> None:
    """Delete one saved checklist by its generated identifier."""
    store_path = path or default_preparation_file()
    records = load_preparations(store_path)
    remaining = [
        record for record in records
        if record["preparation_id"] != preparation_id
    ]
    if len(remaining) == len(records):
        raise ValueError("No saved checklist has that identifier.")
    _write_preparations(store_path, remaining)


def _write_preparations(path: Path, records: list[Preparation]) -> None:
    """Atomically replace the local checklist file after successful encoding."""
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
