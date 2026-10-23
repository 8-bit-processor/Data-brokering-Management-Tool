"""Create app-managed case workspaces with immutable original evidence."""

import hashlib
import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath

from react_framework.agent import AgentActivity, AgentTool
from react_framework.tool_catalog import bind_tool


# Limit which files can be read or searched as plain text by the first version.
TEXT_EVIDENCE_SUFFIXES = {
    ".csv",
    ".json",
    ".log",
    ".md",
    ".py",
    ".rst",
    ".text",
    ".txt",
}
# Keep a single model tool result bounded when a file contains a lot of text.
MAX_REVIEW_BYTES = 512_000
# Bound the number of matching lines returned to the model in one search.
MAX_SEARCH_RESULTS = 100
# Generated reports are deliberately smaller than original evidence files.
MAX_DERIVED_BYTES = 1_000_000


def default_case_root() -> Path:
    """Return the local application-managed location for case folders."""
    local_app_data = os.getenv("LOCALAPPDATA")
    if local_app_data:
        data_root = Path(local_app_data)
    else:
        data_root = Path.home() / ".local" / "share"
    return data_root / "Ollama Internet Databroker Police Agent" / "cases"


class CaseWorkspace:
    """Manage one case's originals, derived files, and local activity log."""

    def __init__(self, case_id: str, case_path: Path) -> None:
        """Open an existing app-managed case directory."""
        self.case_id = self._validate_case_id(case_id)
        self._reject_symlink_chain(case_path)
        self.case_path = case_path.resolve()
        self.originals_path = self.case_path / "originals"
        self.derived_path = self.case_path / "derived"
        self.activity_path = self.case_path / "activity.jsonl"
        self._validate_case_directory()

    @classmethod
    def create(
        cls,
        case_id: str,
        root: Path | None = None,
    ) -> "CaseWorkspace":
        """Create a new local case with separate originals and derived folders."""
        valid_case_id = cls._validate_case_id(case_id)
        case_root = (root or default_case_root()).expanduser()
        cls._reject_symlink_chain(case_root)
        case_root = case_root.resolve()
        case_path = case_root / valid_case_id

        # Never adopt or modify an existing case directory implicitly.
        case_root.mkdir(parents=True, exist_ok=True)
        cls._reject_symlink(case_root)
        case_path.mkdir(exist_ok=False)
        (case_path / "originals").mkdir()
        (case_path / "derived").mkdir()

        # Record basic local workspace metadata as a newly created file.
        metadata = {
            "case_id": valid_case_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        with (case_path / "case.json").open("x", encoding="utf-8") as metadata_file:
            json.dump(metadata, metadata_file, indent=2)
            metadata_file.write("\n")
        return cls(valid_case_id, case_path)

    @classmethod
    def open(
        cls,
        case_id: str,
        root: Path | None = None,
    ) -> "CaseWorkspace":
        """Open a previously created local case by its validated identifier."""
        valid_case_id = cls._validate_case_id(case_id)
        case_root = (root or default_case_root()).expanduser()
        cls._reject_symlink_chain(case_root)
        case_root = case_root.resolve()
        return cls(valid_case_id, case_root / valid_case_id)

    @staticmethod
    def _validate_case_id(case_id: str) -> str:
        """Accept only short filesystem-safe case identifiers."""
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", case_id):
            raise ValueError("Case ID must use 1-64 letters, digits, underscores, or hyphens.")
        return case_id

    @staticmethod
    def _reject_symlink(path: Path) -> None:
        """Reject symbolic links so case operations cannot escape the workspace."""
        if path.is_symlink():
            raise ValueError(f"Symbolic links are not allowed in the case workspace: {path.name}")

    @classmethod
    def _reject_symlink_chain(cls, path: Path) -> None:
        """Reject linked components before resolving a workspace path."""
        absolute_path = path.absolute()
        for component in reversed((absolute_path, *absolute_path.parents)):
            cls._reject_symlink(component)

    def _validate_case_directory(self) -> None:
        """Check that the case structure exists and contains no linked folders."""
        if not self.case_path.is_dir():
            raise FileNotFoundError(f"Case workspace does not exist: {self.case_path}")
        for directory in (self.case_path, self.originals_path, self.derived_path):
            self._reject_symlink(directory)
            if not directory.is_dir():
                raise ValueError(f"Case workspace folder is missing: {directory.name}")

    @staticmethod
    def _relative_parts(relative_path: str) -> tuple[str, ...]:
        """Parse a safe workspace-relative path, rejecting traversal and roots."""
        if not isinstance(relative_path, str) or not relative_path.strip():
            raise ValueError("A non-empty workspace-relative path is required.")
        normalized = relative_path.replace("\\", "/")
        windows_path = PureWindowsPath(normalized)
        if windows_path.is_absolute() or windows_path.drive or normalized.startswith("/"):
            raise ValueError("Absolute paths are not allowed inside a case workspace.")
        parts = tuple(part for part in normalized.split("/") if part)
        if not parts or any(part in {".", ".."} or ":" in part for part in parts):
            raise ValueError("The path must not contain traversal or drive components.")
        if any("\x00" in part for part in parts):
            raise ValueError("Null characters are not allowed in workspace paths.")
        if any(PureWindowsPath(part).is_reserved() for part in parts):
            raise ValueError("Reserved Windows device names are not allowed.")
        return parts

    def _safe_path(self, base: Path, relative_path: str, create_parents: bool = False) -> Path:
        """Resolve a path under an allowed folder and reject linked components."""
        parts = self._relative_parts(relative_path)
        current = base
        for index, part in enumerate(parts):
            current = current / part
            self._reject_symlink(current)
            is_parent = index < len(parts) - 1
            if is_parent and create_parents and not current.exists():
                current.mkdir()
            if is_parent and current.exists() and not current.is_dir():
                raise ValueError(f"Workspace path component is not a directory: {part}")

        resolved = current.resolve()
        if not resolved.is_relative_to(base.resolve()):
            raise ValueError("The requested path is outside its allowed case folder.")
        return resolved

    @staticmethod
    def _sha256(path: Path) -> str:
        """Calculate a stable content identifier without changing the file."""
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for block in iter(lambda: source.read(64 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    def import_original(self, source_path: Path) -> dict:
        """Copy a user-selected source into originals without changing its source.

        This method is intended for a deliberate UI file-picker action, not an
        agent tool: the model must not choose arbitrary host filesystem paths.
        """
        source = source_path.expanduser().resolve(strict=True)
        if not source.is_file():
            raise ValueError("Only a single regular file can be imported.")
        destination = self._safe_path(self.originals_path, source.name)

        # Exclusive creation ensures an import cannot replace an earlier item.
        digest = hashlib.sha256()
        destination_created = False
        try:
            with source.open("rb") as input_file, destination.open("xb") as output_file:
                destination_created = True
                for block in iter(lambda: input_file.read(64 * 1024), b""):
                    output_file.write(block)
                    digest.update(block)
        except Exception:
            # Remove only this operation's newly created partial copy.
            if destination_created and destination.exists():
                destination.unlink()
            raise

        imported_file = {
            "path": f"originals/{destination.name}",
            "size_bytes": destination.stat().st_size,
            "sha256": digest.hexdigest(),
            "source_modified": False,
        }
        self.record_activity(
            AgentActivity.create(
                "Case workspace",
                "evidence.imported",
                f"Copied {imported_file['path']} into originals; source was not modified.",
            )
        )
        return imported_file

    def review_file(self, relative_path: str) -> dict:
        """Read one UTF-8 text evidence file and return its exact source text."""
        source_path = self._original_file(relative_path)
        if source_path.suffix.casefold() not in TEXT_EVIDENCE_SUFFIXES:
            raise ValueError(
                "This file type is not supported for text review yet. "
                "PDF and image extraction are not configured."
            )
        try:
            with source_path.open("rb") as source:
                content_bytes = source.read(MAX_REVIEW_BYTES + 1)
            if len(content_bytes) > MAX_REVIEW_BYTES:
                raise ValueError("Evidence file is too large for one review result.")
            content = content_bytes.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ValueError("Evidence file is not valid UTF-8 text.") from error

        return {
            "path": self._relative_to_case(source_path),
            "sha256": hashlib.sha256(content_bytes).hexdigest(),
            "line_count": len(content.splitlines()),
            "content": content,
        }

    def find_files(self, name_contains: str, limit: int = 50) -> list[dict]:
        """Find original evidence by filename and return path, size, and hash."""
        if not 1 <= limit <= MAX_SEARCH_RESULTS:
            raise ValueError(f"Search limit must be between 1 and {MAX_SEARCH_RESULTS}.")
        self._validate_case_directory()
        needle = name_contains.casefold()
        matches = []
        for candidate in self.originals_path.rglob("*"):
            self._reject_symlink(candidate)
            if not candidate.is_file() or (
                needle and needle not in candidate.name.casefold()
            ):
                continue
            matches.append(
                {
                    "path": self._relative_to_case(candidate),
                    "size_bytes": candidate.stat().st_size,
                    "sha256": self._sha256(candidate),
                }
            )
            if len(matches) >= limit:
                break
        return matches

    def grep_search(
        self,
        query: str,
        case_sensitive: bool = False,
        limit: int = 50,
    ) -> dict:
        """Return exact line citations and report evidence files not searched."""
        if not query:
            raise ValueError("Search text must not be empty.")
        if not 1 <= limit <= MAX_SEARCH_RESULTS:
            raise ValueError(f"Search limit must be between 1 and {MAX_SEARCH_RESULTS}.")

        query_value = query if case_sensitive else query.casefold()
        citations = []
        skipped_files = []
        scanned_files = 0
        for source_path in self.originals_path.rglob("*"):
            self._reject_symlink(source_path)
            if not source_path.is_file():
                continue
            relative_path = self._relative_to_case(source_path)
            if source_path.suffix.casefold() not in TEXT_EVIDENCE_SUFFIXES:
                skipped_files.append(
                    {"path": relative_path, "reason": "unsupported text format"}
                )
                continue
            if source_path.stat().st_size > MAX_REVIEW_BYTES:
                skipped_files.append(
                    {"path": relative_path, "reason": "file exceeds review size limit"}
                )
                continue
            try:
                with source_path.open("rb") as source:
                    content_bytes = source.read(MAX_REVIEW_BYTES + 1)
                if len(content_bytes) > MAX_REVIEW_BYTES:
                    skipped_files.append(
                        {"path": relative_path, "reason": "file exceeds review size limit"}
                    )
                    continue
                lines = content_bytes.decode("utf-8").splitlines()
            except UnicodeDecodeError:
                skipped_files.append(
                    {"path": relative_path, "reason": "file is not valid UTF-8"}
                )
                continue
            scanned_files += 1
            content_sha256 = hashlib.sha256(content_bytes).hexdigest()

            for line_number, line in enumerate(lines, start=1):
                line_value = line if case_sensitive else line.casefold()
                if query_value not in line_value:
                    continue
                citations.append(
                    {
                        "citation": (
                            f"{relative_path}:"
                            f"{line_number} (SHA-256 {content_sha256})"
                        ),
                        "path": relative_path,
                        "line": line_number,
                        "sha256": content_sha256,
                        "quote": line,
                    }
                )
                if len(citations) >= limit:
                    return {
                        "matches": citations,
                        "skipped_files": skipped_files,
                        "scanned_files": scanned_files,
                        "results_truncated": True,
                    }
        return {
            "matches": citations,
            "skipped_files": skipped_files,
            "scanned_files": scanned_files,
            "results_truncated": False,
        }

    def copy_original(self, source_path: str, destination_name: str) -> dict:
        """Copy an original evidence file into derived without replacing files."""
        source = self._original_file(source_path)
        destination = self._safe_path(
            self.derived_path,
            destination_name,
            create_parents=True,
        )
        self._copy_new_file(source, destination)
        return {
            "source_path": self._relative_to_case(source),
            "path": self._relative_to_case(destination),
            "sha256": self._sha256(destination),
            "original_modified": False,
        }

    def write_derived(self, file_name: str, content: str) -> dict:
        """Create a UTF-8 derived file without modifying or replacing anything."""
        if not isinstance(content, str):
            raise ValueError("Derived file content must be text.")
        encoded = content.encode("utf-8")
        if len(encoded) > MAX_DERIVED_BYTES:
            raise ValueError("Derived file exceeds the 1 MB limit.")
        destination = self._safe_path(
            self.derived_path,
            file_name,
            create_parents=True,
        )

        # Exclusive mode refuses to overwrite existing derived or evidence files.
        with destination.open("xb") as output_file:
            output_file.write(encoded)
        return {
            "path": self._relative_to_case(destination),
            "size_bytes": len(encoded),
            "sha256": hashlib.sha256(encoded).hexdigest(),
            "originals_modified": False,
        }

    def record_activity(self, activity: AgentActivity) -> None:
        """Show an agent event and append a content-free record to the case log."""
        self._validate_case_directory()
        self._reject_symlink(self.activity_path)
        record = {
            "timestamp": activity.timestamp,
            "agent": activity.agent_name,
            "event": activity.event,
            "detail": activity.detail,
        }
        # The audit log contains action metadata only, never prompts or documents.
        with self.activity_path.open("a", encoding="utf-8") as activity_file:
            activity_file.write(json.dumps(record, ensure_ascii=False) + "\n")
        print(f"[{activity.timestamp}] {activity.agent_name}: {activity.detail}")

    def _original_file(self, relative_path: str) -> Path:
        """Resolve a read-only path and ensure it names an original file."""
        parts = self._relative_parts(relative_path)
        if parts[0] == "originals":
            parts = parts[1:]
        if not parts:
            raise ValueError("Specify a file within the originals folder.")
        source = self._safe_path(self.originals_path, "/".join(parts))
        if not source.is_file():
            raise FileNotFoundError(f"Original evidence file not found: {relative_path}")
        return source

    def _case_path_from_original(self, case_relative_path: str) -> Path:
        """Resolve a listed originals path and reject paths in other folders."""
        parts = self._relative_parts(case_relative_path)
        if parts[0] != "originals" or len(parts) < 2:
            raise ValueError("Evidence search can read only the originals folder.")
        return self._original_file("/".join(parts[1:]))

    def _relative_to_case(self, path: Path) -> str:
        """Return a stable forward-slash path relative to this case directory."""
        return path.relative_to(self.case_path).as_posix()

    @staticmethod
    def _copy_new_file(source: Path, destination: Path) -> None:
        """Copy bytes to a new destination and remove only a failed partial copy."""
        destination_created = False
        try:
            with source.open("rb") as input_file, destination.open("xb") as output_file:
                destination_created = True
                shutil.copyfileobj(input_file, output_file)
        except Exception:
            if destination_created and destination.exists():
                destination.unlink()
            raise


def create_workspace_tools(
    workspace: CaseWorkspace,
    selected_names: tuple[str, ...] = (
        "review_evidence_file",
        "find_evidence_files",
        "grep_search",
        "copy_original_file",
        "write_derived_file",
    ),
) -> tuple[AgentTool, ...]:
    """Bind the central file-tool schemas to this case's local workspace.

    Modules choose which returned tools to pass to their own agent. These
    handlers are generic workspace operations; they cannot access other cases.
    """
    available_handlers = {
        "review_evidence_file": lambda arguments: workspace.review_file(arguments["path"]),
        "find_evidence_files": lambda arguments: workspace.find_files(
            arguments["name_contains"],
            arguments["limit"],
        ),
        "grep_search": lambda arguments: workspace.grep_search(
            arguments["query"],
            arguments["case_sensitive"],
            arguments["limit"],
        ),
        "copy_original_file": lambda arguments: workspace.copy_original(
            arguments["source_path"],
            arguments["destination_name"],
        ),
        "write_derived_file": lambda arguments: workspace.write_derived(
            arguments["file_name"],
            arguments["content"],
        ),
    }
    tools = []
    for name in selected_names:
        if name not in available_handlers:
            raise ValueError(f"Unknown workspace tool: {name!r}.")
        tools.append(bind_tool(name, available_handlers[name]))
    return tuple(tools)
