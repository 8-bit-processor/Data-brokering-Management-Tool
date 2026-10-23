"""Load the reviewed public sources used to discover data-broker records."""

import ipaddress
import csv
import hashlib
import io
import json
import os
from datetime import date, datetime, timezone
from pathlib import Path
import re
import tempfile
from typing import Literal, NoReturn, TypedDict, cast
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener
from urllib.parse import urlsplit

from ollama_databroker_compliance_agent.directory import default_app_data_dir


class DiscoverySource(TypedDict):
    """Describe a public source relevant to broker discovery or opt-out."""

    source_id: str
    name: str
    source_type: Literal["registry", "registry_guidance", "multi_broker_portal"]
    jurisdictions: list[str]
    sectors: list[str]
    source_url: str
    download_url: str
    checked_at: str
    what_it_covers: str
    limitations: str
    app_handling: str


class UserDiscoverySource(TypedDict):
    """Describe a public source configured and reviewed by the user."""

    source_id: str
    name: str
    source_type: Literal["csv_registry", "html_directory"]
    source_url: str
    coverage: str
    limitations: str
    terms_reviewed: bool


class BrokerCandidate(TypedDict):
    """Retain only public business identifiers from a reviewed registry row."""

    candidate_id: str
    name: str
    dba: str
    primary_website: str
    consumer_rights_website: str


class CandidateSnapshot(TypedDict):
    """Describe a local, minimized snapshot of California registry entries."""

    source_id: str
    source_url: str
    retrieved_at: str
    source_sha256: str
    candidate_count: int
    candidates: list[BrokerCandidate]


DISCOVERY_SOURCES_FILE = Path(__file__).with_name("broker_discovery_sources.json")
USER_DISCOVERY_SOURCES_FILE = "broker_user_discovery_sources.json"
CALIFORNIA_SOURCE_ID = "california_data_broker_registry"
MAX_REGISTRY_BYTES = 2_000_000
MAX_REGISTRY_ROWS = 10_000
MAX_CELL_LENGTH = 2_000
MAX_USER_DISCOVERY_SOURCES = 100
MAX_USER_SOURCE_TEXT_LENGTH = 2_000
REGISTRY_NAME_COLUMN = "Data broker name:"
REGISTRY_DBA_COLUMN = "Doing Business As (DBA), if applicable:"
REGISTRY_WEBSITE_COLUMN = "Data broker primary website:"
REGISTRY_RIGHTS_WEBSITE_COLUMN = (
    "Data broker's primary website that contains details on how consumers can "
    "exercise their CA Consumer Privacy rights:"
)


def default_candidate_snapshot_file() -> Path:
    """Return local storage for public registry candidate metadata."""
    return default_app_data_dir() / "broker_registry_candidates.json"


def default_user_discovery_sources_file() -> Path:
    """Return local storage for user-managed public discovery sources."""
    return default_app_data_dir() / USER_DISCOVERY_SOURCES_FILE


class _NoRedirectHandler(HTTPRedirectHandler):
    """Require the approved registry endpoint to remain the download host."""

    def redirect_request(
        self,
        req: Request,
        fp: object,
        code: int,
        msg: str,
        headers: object,
        newurl: str,
    ) -> NoReturn:
        del req, fp, code, msg, headers, newurl
        raise ValueError("The registry download redirected; no redirect destination was contacted.")


def _text_field(source: dict[str, object], field: str) -> str:
    value = source.get(field)
    if not isinstance(value, str):
        raise ValueError(f"Discovery source field {field!r} must contain text.")
    return value


def _label_list(source: dict[str, object], field: str, source_id: str) -> list[str]:
    values = source.get(field)
    if not isinstance(values, list) or not values:
        raise ValueError(f"Discovery source {source_id!r} needs non-empty {field} labels.")
    labels: list[str] = []
    raw_values = cast(list[object], values)
    for value in raw_values:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(
                f"Discovery source {source_id!r} needs non-empty {field} labels."
            )
        labels.append(value)
    return labels


def _is_public_https_url(value: str) -> bool:
    try:
        parsed_url = urlsplit(value)
        port = parsed_url.port
    except ValueError:
        return False
    hostname = parsed_url.hostname
    try:
        is_ip_address = hostname is not None and ipaddress.ip_address(hostname)
    except ValueError:
        is_ip_address = False
    return not (
        parsed_url.scheme != "https"
        or hostname is None
        or parsed_url.username is not None
        or parsed_url.password is not None
        or port not in (None, 443)
        or is_ip_address
        or hostname.casefold() == "localhost"
        or hostname.casefold().endswith((".localhost", ".local"))
    )


def load_discovery_sources(
    path: Path = DISCOVERY_SOURCES_FILE,
) -> list[DiscoverySource]:
    """Load and validate the source inventory shipped with the application."""
    try:
        with path.open(encoding="utf-8") as source_file:
            sources: object = json.load(source_file)
    except FileNotFoundError:
        raise
    except json.JSONDecodeError as error:
        raise ValueError(f"Discovery source inventory contains invalid JSON: {path}") from error
    return validate_discovery_sources(sources)


def validate_user_discovery_sources(
    sources: object,
) -> list[UserDiscoverySource]:
    """Validate user-managed sources before displaying or using them."""
    if not isinstance(sources, list):
        raise ValueError("User-managed discovery sources must be a JSON array.")
    validated: list[UserDiscoverySource] = []
    seen_ids: set[str] = set()
    seen_urls: set[str] = set()
    for raw_source in cast(list[object], sources):
        if not isinstance(raw_source, dict):
            raise ValueError("User-managed discovery sources must be JSON objects.")
        source = cast(dict[object, object], raw_source)
        if not all(isinstance(key, str) for key in source):
            raise ValueError("User-managed source field names must be text.")
        source = cast(dict[str, object], source)
        if set(source) != set(UserDiscoverySource.__annotations__):
            raise ValueError("User-managed source has missing or unexpected fields.")
        source_id = source["source_id"]
        name = source["name"]
        source_type = source["source_type"]
        source_url = source["source_url"]
        coverage = source["coverage"]
        limitations = source["limitations"]
        terms_reviewed = source["terms_reviewed"]
        if (
            not isinstance(source_id, str)
            or not re.fullmatch(r"[0-9a-f]{32}", source_id)
            or source_id in seen_ids
            or not isinstance(name, str)
            or not name.strip()
            or len(name) > MAX_USER_SOURCE_TEXT_LENGTH
            or not isinstance(source_type, str)
            or source_type not in {"csv_registry", "html_directory"}
            or not isinstance(source_url, str)
            or not _is_public_https_url(source_url)
            or len(source_url) > MAX_USER_SOURCE_TEXT_LENGTH
            or source_url in seen_urls
            or not isinstance(coverage, str)
            or not coverage.strip()
            or len(coverage) > MAX_USER_SOURCE_TEXT_LENGTH
            or not isinstance(limitations, str)
            or not limitations.strip()
            or len(limitations) > MAX_USER_SOURCE_TEXT_LENGTH
            or not isinstance(terms_reviewed, bool)
            or not terms_reviewed
        ):
            raise ValueError(
                "User-managed sources need a unique ID, name, supported format, "
                "public HTTPS URL, coverage, limitations, and reviewed source terms."
            )
        if any(
            ord(character) < 32
            for field in (name, source_url, coverage, limitations)
            for character in field
        ):
            raise ValueError("User-managed source fields cannot contain control characters.")
        seen_ids.add(source_id)
        seen_urls.add(source_url)
        validated.append(
            {
                "source_id": source_id,
                "name": name.strip(),
                "source_type": cast(Literal["csv_registry", "html_directory"], source_type),
                "source_url": source_url.strip(),
                "coverage": coverage.strip(),
                "limitations": limitations.strip(),
                "terms_reviewed": terms_reviewed,
            }
        )
    if len(validated) > MAX_USER_DISCOVERY_SOURCES:
        raise ValueError(
            f"At most {MAX_USER_DISCOVERY_SOURCES} user-managed sources are supported."
        )
    return validated


def load_user_discovery_sources(
    path: Path | None = None,
) -> list[UserDiscoverySource]:
    """Load user-managed public discovery sources from local storage."""
    source_path = path or default_user_discovery_sources_file()
    try:
        with source_path.open(encoding="utf-8") as source_file:
            sources: object = json.load(source_file)
    except FileNotFoundError:
        return []
    except json.JSONDecodeError as error:
        raise ValueError(
            f"Saved user-managed discovery sources contain invalid JSON: {source_path}"
        ) from error
    return validate_user_discovery_sources(sources)


def save_user_discovery_sources(
    sources: list[UserDiscoverySource],
    path: Path | None = None,
) -> None:
    """Atomically save validated user-managed discovery sources locally."""
    validated = validate_user_discovery_sources(sources)
    source_path = path or default_user_discovery_sources_file()
    source_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=source_path.parent,
            prefix=f".{source_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as source_file:
            temporary_path = Path(source_file.name)
            json.dump(validated, source_file, ensure_ascii=False, indent=2)
            source_file.flush()
            os.fsync(source_file.fileno())
        os.replace(temporary_path, source_path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def validate_discovery_sources(sources: object) -> list[DiscoverySource]:
    """Reject incomplete or unsafe source metadata before it is shown to users."""
    if not isinstance(sources, list):
        raise ValueError("Discovery source inventory must contain a JSON array.")
    expected_fields = set(DiscoverySource.__annotations__)
    seen_ids: set[str] = set()
    validated: list[DiscoverySource] = []
    raw_sources = cast(list[object], sources)

    for raw_source in raw_sources:
        if not isinstance(raw_source, dict):
            raise ValueError("Discovery sources must be JSON objects.")
        raw_mapping = cast(dict[object, object], raw_source)
        if not all(isinstance(key, str) for key in raw_mapping):
            raise ValueError("Discovery source field names must be text.")
        source = cast(dict[str, object], raw_mapping)
        if set(source) != expected_fields:
            raise ValueError("Discovery source has missing or unexpected fields.")
        source_id = _text_field(source, "source_id").strip()
        name = _text_field(source, "name")
        source_type_value = _text_field(source, "source_type")
        source_url = _text_field(source, "source_url")
        checked_at = _text_field(source, "checked_at")
        what_it_covers = _text_field(source, "what_it_covers")
        limitations = _text_field(source, "limitations")
        app_handling = _text_field(source, "app_handling")
        if not source_id or source_id in seen_ids:
            raise ValueError("Discovery source identifiers must be non-empty and unique.")
        seen_ids.add(source_id)
        if (
            not name.strip()
            or not what_it_covers.strip()
            or not limitations.strip()
            or not app_handling.strip()
        ):
            raise ValueError(f"Discovery source {source_id!r} is incomplete.")
        source_type: Literal["registry", "registry_guidance", "multi_broker_portal"]
        source_url = _text_field(source, "source_url")
        download_url = _text_field(source, "download_url")
        if source_type_value == "registry":
            source_type = "registry"
        elif source_type_value == "registry_guidance":
            source_type = "registry_guidance"
        elif source_type_value == "multi_broker_portal":
            source_type = "multi_broker_portal"
        else:
            raise ValueError(f"Discovery source {source_id!r} has an unknown source type.")
        jurisdictions = _label_list(source, "jurisdictions", source_id)
        sectors = _label_list(source, "sectors", source_id)

        if not _is_public_https_url(source_url):
            raise ValueError(f"Discovery source {source_id!r} needs a public HTTPS URL.")
        if download_url and not _is_public_https_url(download_url):
            raise ValueError(f"Discovery source {source_id!r} has an unsafe download URL.")
        try:
            date.fromisoformat(checked_at)
        except ValueError as error:
            raise ValueError(
                f"Discovery source {source_id!r} needs a valid ISO check date."
            ) from error
        validated.append(
            {
                "source_id": source_id,
                "name": name,
                "source_type": source_type,
                "jurisdictions": jurisdictions,
                "sectors": sectors,
                "source_url": source_url,
                "download_url": download_url,
                "checked_at": checked_at,
                "what_it_covers": what_it_covers,
                "limitations": limitations,
                "app_handling": app_handling,
            }
        )
    return validated


def _clean_cell(value: str | None, field: str, *, required: bool = False) -> str:
    cleaned = " ".join((value or "").split())
    if len(cleaned) > MAX_CELL_LENGTH:
        raise ValueError(f"California registry field {field!r} exceeds the supported length.")
    if required and not cleaned:
        raise ValueError(f"California registry row is missing {field!r}.")
    if any(ord(character) < 32 for character in cleaned):
        raise ValueError(f"California registry field {field!r} contains control characters.")
    return cleaned


def _candidate_id(name: str, dba: str, website: str, rights_website: str) -> str:
    identity = "\0".join(
        value.casefold() for value in (name, dba, website, rights_website)
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]


def parse_california_registry_csv(
    content: bytes,
    *,
    retrieved_at: str | None = None,
) -> CandidateSnapshot:
    """Parse the official CSV while discarding contacts and sensitive disclosures."""
    if len(content) > MAX_REGISTRY_BYTES:
        raise ValueError("California registry download exceeds the supported size.")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError("California registry download is not valid UTF-8.") from error

    reader = csv.DictReader(io.StringIO(text))
    required_columns = {
        REGISTRY_NAME_COLUMN,
        REGISTRY_DBA_COLUMN,
        REGISTRY_WEBSITE_COLUMN,
        REGISTRY_RIGHTS_WEBSITE_COLUMN,
    }
    if reader.fieldnames is None or not required_columns.issubset(reader.fieldnames):
        raise ValueError("California registry CSV has an unexpected schema.")

    candidates_by_id: dict[str, BrokerCandidate] = {}
    for row_number, row in enumerate(reader, start=1):
        if row_number > MAX_REGISTRY_ROWS:
            raise ValueError("California registry CSV exceeds the supported row count.")
        name = _clean_cell(row.get(REGISTRY_NAME_COLUMN), REGISTRY_NAME_COLUMN, required=True)
        dba = _clean_cell(row.get(REGISTRY_DBA_COLUMN), REGISTRY_DBA_COLUMN)
        website = _clean_cell(row.get(REGISTRY_WEBSITE_COLUMN), REGISTRY_WEBSITE_COLUMN)
        rights_website = _clean_cell(
            row.get(REGISTRY_RIGHTS_WEBSITE_COLUMN),
            REGISTRY_RIGHTS_WEBSITE_COLUMN,
        )
        candidate_id = _candidate_id(name, dba, website, rights_website)
        candidates_by_id.setdefault(
            candidate_id,
            {
                "candidate_id": candidate_id,
                "name": name,
                "dba": dba,
                "primary_website": website,
                "consumer_rights_website": rights_website,
            },
        )
    if not candidates_by_id:
        raise ValueError("California registry CSV contains no broker rows.")

    source = next(
        (
            item for item in DISCOVERY_SOURCES
            if item["source_id"] == CALIFORNIA_SOURCE_ID
        ),
        None,
    )
    if source is None or not source["download_url"]:
        raise ValueError("California registry download source is not configured.")
    return {
        "source_id": CALIFORNIA_SOURCE_ID,
        "source_url": source["download_url"],
        "retrieved_at": retrieved_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_sha256": hashlib.sha256(content).hexdigest(),
        "candidate_count": len(candidates_by_id),
        "candidates": list(candidates_by_id.values()),
    }


def _validate_candidate_snapshot(value: object) -> CandidateSnapshot:
    if not isinstance(value, dict):
        raise ValueError("Saved broker-candidate snapshot must be a JSON object.")
    snapshot = cast(dict[object, object], value)
    expected_fields = {
        "source_id",
        "source_url",
        "retrieved_at",
        "source_sha256",
        "candidate_count",
        "candidates",
    }
    if not all(isinstance(key, str) for key in snapshot):
        raise ValueError("Saved broker-candidate field names must be text.")
    snapshot = cast(dict[str, object], snapshot)
    if set(snapshot) != expected_fields:
        raise ValueError("Saved broker-candidate snapshot has unexpected fields.")
    source_id = snapshot["source_id"]
    source_url = snapshot["source_url"]
    retrieved_at = snapshot["retrieved_at"]
    source_sha256 = snapshot["source_sha256"]
    candidate_count = snapshot["candidate_count"]
    raw_candidates = snapshot["candidates"]
    if (
        source_id != CALIFORNIA_SOURCE_ID
        or not isinstance(source_url, str)
        or not _is_public_https_url(source_url)
        or not isinstance(retrieved_at, str)
        or not isinstance(source_sha256, str)
        or not re.fullmatch(r"[0-9a-f]{64}", source_sha256)
        or not isinstance(candidate_count, int)
        or isinstance(candidate_count, bool)
        or not isinstance(raw_candidates, list)
    ):
        raise ValueError("Saved broker-candidate snapshot contains invalid metadata.")
    try:
        datetime.fromisoformat(retrieved_at)
    except ValueError as error:
        raise ValueError("Saved broker-candidate snapshot has an invalid retrieval date.") from error

    candidates: list[BrokerCandidate] = []
    candidate_ids: set[str] = set()
    for raw_candidate in cast(list[object], raw_candidates):
        if not isinstance(raw_candidate, dict):
            raise ValueError("Saved broker-candidate entries must be JSON objects.")
        candidate = cast(dict[object, object], raw_candidate)
        if not all(isinstance(key, str) for key in candidate):
            raise ValueError("Saved broker-candidate field names must be text.")
        candidate = cast(dict[str, object], candidate)
        if set(candidate) != {
            "candidate_id",
            "name",
            "dba",
            "primary_website",
            "consumer_rights_website",
        }:
            raise ValueError("Saved broker-candidate entry has unexpected fields.")
        candidate_id = candidate["candidate_id"]
        name = candidate["name"]
        dba = candidate["dba"]
        website = candidate["primary_website"]
        rights_website = candidate["consumer_rights_website"]
        if (
            not isinstance(candidate_id, str)
            or not re.fullmatch(r"[0-9a-f]{20}", candidate_id)
            or candidate_id in candidate_ids
            or not isinstance(name, str)
            or not name.strip()
            or not isinstance(dba, str)
            or not isinstance(website, str)
            or not isinstance(rights_website, str)
            or any(len(field) > MAX_CELL_LENGTH for field in (name, dba, website, rights_website))
        ):
            raise ValueError("Saved broker-candidate entry contains invalid fields.")
        candidate_ids.add(candidate_id)
        candidates.append(
            {
                "candidate_id": candidate_id,
                "name": name,
                "dba": dba,
                "primary_website": website,
                "consumer_rights_website": rights_website,
            }
        )
    if candidate_count != len(candidates):
        raise ValueError("Saved broker-candidate count does not match its records.")
    return {
        "source_id": CALIFORNIA_SOURCE_ID,
        "source_url": source_url,
        "retrieved_at": retrieved_at,
        "source_sha256": source_sha256,
        "candidate_count": candidate_count,
        "candidates": candidates,
    }


def load_candidate_snapshot(
    path: Path | None = None,
) -> CandidateSnapshot | None:
    """Load the local public candidate snapshot, if one has been imported."""
    snapshot_path = path or default_candidate_snapshot_file()
    try:
        with snapshot_path.open(encoding="utf-8") as snapshot_file:
            snapshot: object = json.load(snapshot_file)
    except FileNotFoundError:
        return None
    except json.JSONDecodeError as error:
        raise ValueError(f"Saved broker-candidate snapshot contains invalid JSON: {snapshot_path}") from error
    return _validate_candidate_snapshot(snapshot)


def save_candidate_snapshot(
    snapshot: CandidateSnapshot,
    path: Path | None = None,
) -> None:
    """Atomically persist minimized public registry candidate metadata."""
    snapshot = _validate_candidate_snapshot(snapshot)
    snapshot_path = path or default_candidate_snapshot_file()
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=snapshot_path.parent,
            prefix=f".{snapshot_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as snapshot_file:
            temporary_path = Path(snapshot_file.name)
            json.dump(snapshot, snapshot_file, ensure_ascii=False, indent=2)
            snapshot_file.flush()
            os.fsync(snapshot_file.fileno())
        os.replace(temporary_path, snapshot_path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def refresh_california_candidates(
    path: Path | None = None,
    *,
    approved: bool = False,
) -> CandidateSnapshot:
    """Fetch and save the California registry after explicit user approval."""
    if not approved:
        raise ValueError("Explicit user approval is required before downloading the registry.")
    source = next(
        (
            item for item in DISCOVERY_SOURCES
            if item["source_id"] == CALIFORNIA_SOURCE_ID
        ),
        None,
    )
    if source is None or not source["download_url"]:
        raise ValueError("California registry download source is not configured.")
    request = Request(
        source["download_url"],
        headers={"User-Agent": "LocalDataBrokerAssistant/1.0"},
    )
    opener = build_opener(_NoRedirectHandler)
    try:
        with opener.open(request, timeout=30) as response:
            if response.headers.get_content_type() != "text/csv":
                raise ValueError("California registry download did not return a CSV file.")
            content = response.read(MAX_REGISTRY_BYTES + 1)
    except (HTTPError, URLError, OSError) as error:
        raise OSError(f"Unable to download the California registry: {error}") from error
    snapshot = parse_california_registry_csv(content)
    save_candidate_snapshot(snapshot, path)
    return snapshot


DISCOVERY_SOURCES: list[DiscoverySource] = load_discovery_sources()
