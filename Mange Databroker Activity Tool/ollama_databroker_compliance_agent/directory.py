"""Maintain and search the application's manually vetted broker directory."""

import ipaddress
import json
import os
from datetime import date
from pathlib import Path
from typing import TypedDict
from urllib.parse import urlsplit


class BrokerRecord(TypedDict):
    """Describe one broker's reviewed, public opt-out information."""

    # Stable internal key used to select this record for app operations.
    broker_id: str
    # Broker name as it should appear in the user interface.
    broker: str
    # Region labels that are eligible to match the user's region.
    regions: list[str]
    # Public opt-out channel described by the official source.
    opt_out_method: str
    # Official opt-out page where the user can follow the process.
    opt_out_url: str
    # Human-readable steps taken from or summarized from the official source.
    instructions: str
    # HTTPS URL where the user can verify the broker's opt-out process.
    source_url: str
    # Date the source and instructions were last checked.
    verified_at: str


DIRECTORY_FILE = Path(__file__).with_name("broker_directory.json")


def default_app_data_dir() -> Path:
    """Return the user's local application-data directory."""
    local_app_data = os.getenv("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "Ollama Internet Databroker Police Agent"
    data_root = Path(os.getenv("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return data_root / "Ollama Internet Databroker Police Agent"


def default_directory_override_file() -> Path:
    """Return the user-writable, approved broker-directory override file."""
    return default_app_data_dir() / "broker_directory_overrides.json"


def _read_record_file(path: Path, description: str) -> list[BrokerRecord]:
    try:
        with path.open(encoding="utf-8") as directory_file:
            records = json.load(directory_file)
    except FileNotFoundError:
        raise
    except json.JSONDecodeError as error:
        raise ValueError(f"{description} contains invalid JSON: {path}") from error
    if not isinstance(records, list):
        raise ValueError(f"{description} must contain a JSON array.")
    return records


def load_directory(path: Path = DIRECTORY_FILE) -> list[BrokerRecord]:
    """Load the shipped directory plus any user-approved local overrides."""
    records = _read_record_file(path, "Broker directory")
    if path != DIRECTORY_FILE:
        validate_directory(records)
        return records
    validate_directory(records)
    try:
        overrides = load_directory_overrides()
    except FileNotFoundError:
        overrides = []
    merged_records = [dict(record) for record in records]
    indices = {record["broker_id"]: index for index, record in enumerate(merged_records)}
    for override in overrides:
        if override["broker_id"] in indices:
            merged_records[indices[override["broker_id"]]] = dict(override)
        else:
            indices[override["broker_id"]] = len(merged_records)
            merged_records.append(dict(override))
    validate_directory(merged_records)
    return merged_records


def load_directory_overrides(
    path: Path | None = None,
) -> list[BrokerRecord]:
    """Load and validate approved user-local broker record overrides."""
    override_path = path or default_directory_override_file()
    overrides = _read_record_file(override_path, "Broker directory override")
    validate_directory(overrides)
    return overrides


def validate_directory(records: list[BrokerRecord] | None = None) -> None:
    """Raise ValueError when a broker record is incomplete or unsafe to render."""
    records = BROKER_DIRECTORY if records is None else records
    # Track identifiers already seen so each record can be selected unambiguously.
    seen_ids: set[str] = set()
    # Require the record schema to stay synchronized with BrokerRecord.
    required_fields = set(BrokerRecord.__annotations__)

    # Validate every entry before exposing its public guidance.
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("Broker directory entries must be JSON objects.")
        # Current broker entry being checked against the directory schema.
        if set(record) != required_fields:
            raise ValueError("Broker directory record has missing or unexpected fields.")
        if not isinstance(record["broker_id"], str):
            raise ValueError("Broker directory identifiers must be text.")
        # Normalize whitespace before checking the record's stable identifier.
        broker_id = record["broker_id"].strip()
        if not broker_id or broker_id in seen_ids:
            raise ValueError("Broker directory contains a missing or duplicate broker_id.")
        # Reserve this identifier so later records cannot reuse it.
        seen_ids.add(broker_id)

        for field in ("broker", "opt_out_method", "instructions", "source_url",
                      "opt_out_url", "verified_at"):
            if not isinstance(record[field], str):
                raise ValueError(f"Broker record {broker_id!r} has an invalid {field}.")
        if (
            not record["broker"].strip()
            or not isinstance(record["regions"], list)
            or not record["regions"]
            or any(not isinstance(region, str) or not region.strip() for region in record["regions"])
            or not record["opt_out_method"].strip()
            or not record["instructions"].strip()
        ):
            raise ValueError(
                f"Broker record {broker_id!r} needs a name, regions, method, and instructions."
            )
        for field in ("source_url", "opt_out_url"):
            parsed_url = urlsplit(record[field])
            hostname = parsed_url.hostname
            try:
                is_ip_address = hostname is not None and ipaddress.ip_address(hostname)
            except ValueError:
                is_ip_address = False
            if (
                parsed_url.scheme != "https"
                or hostname is None
                or parsed_url.username is not None
                or parsed_url.password is not None
                or parsed_url.port not in (None, 443)
                or parsed_url.query
                or parsed_url.fragment
                or is_ip_address
                or hostname.casefold() == "localhost"
                or hostname.casefold().endswith((".localhost", ".local"))
            ):
                raise ValueError(
                    f"Broker record {broker_id!r} needs a public HTTPS {field}."
                )
        try:
            date.fromisoformat(record["verified_at"])
        except ValueError as error:
            raise ValueError(
                f"Broker record {broker_id!r} needs a valid ISO verification date."
            ) from error


# This file contains reviewed public broker instructions, not user case data.
BROKER_DIRECTORY: list[BrokerRecord] = load_directory()


def find_brokers(region: str) -> dict:
    """Return vetted public records whose region label matches the user's input.

    Args:
        region: Region label to match, such as a country or state.

    Returns:
        A dictionary containing the matching public broker records.

    Raises:
        ValueError: If the region is empty or longer than 100 characters.
    """
    # Refuse to search malformed directory entries rather than returning
    # incomplete guidance as if it were verified.
    validate_directory()
    if not region.strip() or len(region) > 100:
        raise ValueError("Region must contain 1 to 100 characters.")
    # Case-fold so region matching is not sensitive to letter casing.
    normalized_region = region.strip().casefold()
    if normalized_region in {"us", "usa", "united states of america"}:
        normalized_region = "united states"
    # Return only the public guidance needed by the caller.
    matches = [
        {
            "broker_id": record["broker_id"],
            "broker": record["broker"],
            "regions": record["regions"],
            "opt_out_method": record["opt_out_method"],
            "opt_out_url": record["opt_out_url"],
            "instructions": record["instructions"],
            "source_url": record["source_url"],
            "verified_at": record["verified_at"],
        }
        # Consider each maintained record and compare normalized region labels.
        # Candidate broker record being compared with the requested region.
        for record in BROKER_DIRECTORY
        # Region label under evaluation for the current candidate.
        # Compare the requested label with this record's configured regions.
        if normalized_region in {value.strip().casefold() for value in record["regions"]}
    ]
    return {"matches": matches}
