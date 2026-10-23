"""Central catalog of tool schemas available to module-owned ReAct agents."""

from copy import deepcopy
from collections.abc import Callable

from react_framework.agent import AgentTool


# Store shared schemas here, but keep each tool's behavior in its feature
# module. An agent sends only tools that its module explicitly binds and passes.
TOOL_CATALOG: dict[str, dict] = {
    "find_brokers": {
        "description": "Look up vetted broker instructions for the user's region.",
        "parameters": {
            "type": "object",
            "properties": {"region": {"type": "string"}},
            "required": ["region"],
            "additionalProperties": False,
        },
    },
    "list_broker_discovery_sources": {
        "description": "List the reviewed public discovery sources and their stated coverage limitations.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
    },
    "search_registry_candidates": {
        "description": "Search the locally imported California registry candidate snapshot by broker or business name. Candidates are not verified opt-out instructions.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": ["query", "limit"],
            "additionalProperties": False,
        },
    },
    "get_opt_out_compliance_status": {
        "description": "Read local user-entered opt-out case statuses and return a cautious progress report. Does not contact brokers or verify compliance.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
    },
    "record_opt_out_case_status": {
        "description": "Record a status the user explicitly reports for a saved local opt-out case. This does not verify broker conduct.",
        "parameters": {
            "type": "object",
            "properties": {
                "case_id": {"type": "string"},
                "status": {
                    "type": "string",
                    "enum": [
                        "prepared",
                        "in_progress",
                        "awaiting_user_verification",
                        "submission_initiated",
                        "acknowledged",
                        "response_received",
                        "user_reports_removed",
                        "user_reports_not_removed",
                    ],
                },
            },
            "required": ["case_id", "status"],
            "additionalProperties": False,
        },
    },
    "perform_broker_case_action": {
        "description": "Carry out a user-authorized visible broker contact or listing recheck for a maintained broker. Personal listing and contact details are collected by the app UI and are not tool arguments.",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["contact_broker", "recheck_listing"],
                },
                "broker_id": {"type": "string", "enum": ["whitepages", "spokeo"]},
            },
            "required": ["action", "broker_id"],
            "additionalProperties": False,
        },
    },
    "review_user_selected_evidence": {
        "description": "Review a user-selected, imported text evidence file for the active local opt-out case. File contents are sent only to local Ollama for analysis.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
    },
    "consult_data_impact_expert": {
        "description": "Consult the local privacy impact analysis specialist using only the user's current message. Case evidence is unavailable unless the user separately approves its review.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
    },
    "search_public_broker_sources": {
        "description": "Search approved public sources for general broker directories, opt-out guides, official registries, or enforcement information. The app sends a fixed non-identifying query only after user approval; never search for a person's footprint.",
        "parameters": {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "enum": [
                        "broker_directories",
                        "opt_out_guides",
                        "official_registries",
                        "enforcement_actions",
                    ],
                },
                "limit": {"type": "integer"},
            },
            "required": ["topic", "limit"],
            "additionalProperties": False,
        },
    },
    "fetch_official_broker_page": {
        "description": "After the application obtains explicit user approval, fetch one page URL already listed in the vetted broker directory and compare it with the prior local snapshot. This tool is read-only and cannot change directory records.",
        "parameters": {
            "type": "object",
            "properties": {
                "broker_id": {"type": "string"},
                "page_kind": {
                    "type": "string",
                    "enum": ["instructions", "opt_out"],
                },
            },
            "required": ["broker_id", "page_kind"],
            "additionalProperties": False,
        },
    },
    "review_evidence_file": {
        "description": "Read a supported UTF-8 evidence file from the read-only originals folder.",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
            "additionalProperties": False,
        },
    },
    "read_impact_timeline": {
        "description": "Read user-entered, case-local impact timeline events and their evidence references. Events are user-reported, not independently verified.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
    },
    "find_evidence_files": {
        "description": "Find original evidence files by filename; an empty name filter lists the first files in this case.",
        "parameters": {
            "type": "object",
            "properties": {
                "name_contains": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": ["name_contains", "limit"],
            "additionalProperties": False,
        },
    },
    "grep_search": {
        "description": "Search original UTF-8 text evidence and return exact quotes with file citations and line numbers.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "case_sensitive": {"type": "boolean"},
                "limit": {"type": "integer"},
            },
            "required": ["query", "case_sensitive", "limit"],
            "additionalProperties": False,
        },
    },
    "copy_original_file": {
        "description": "Copy an original evidence file to a new path in the derived folder; never overwrite.",
        "parameters": {
            "type": "object",
            "properties": {
                "source_path": {"type": "string"},
                "destination_name": {"type": "string"},
            },
            "required": ["source_path", "destination_name"],
            "additionalProperties": False,
        },
    },
    "write_derived_file": {
        "description": "Create a new UTF-8 file in the derived folder; never modify originals or overwrite.",
        "parameters": {
            "type": "object",
            "properties": {
                "file_name": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["file_name", "content"],
            "additionalProperties": False,
        },
    },
    "invoke_research_agent": {
        "description": "Ask the local research specialist to prepare a non-identifying public-source research plan; live web search is not configured.",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    "search_public_sources": {
        "description": "Search publicly accessible sources using a non-identifying query through a configured public-search provider.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": ["query", "limit"],
            "additionalProperties": False,
        },
    },
    "invoke_architect_agent": {
        "description": "Ask the independent local architecture specialist to review a technical design task.",
        "parameters": {
            "type": "object",
            "properties": {"task": {"type": "string"}},
            "required": ["task"],
            "additionalProperties": False,
        },
    },
    "invoke_legal_agent": {
        "description": "Ask the local preliminary legal-analysis specialist to review supplied case context and identify questions for professional counsel.",
        "parameters": {
            "type": "object",
            "properties": {
                "question": {"type": "string"},
                "jurisdiction": {"type": "string"},
                "case_context": {"type": "string"},
            },
            "required": ["question", "jurisdiction", "case_context"],
            "additionalProperties": False,
        },
    },
}


def bind_tool(name: str, handler: Callable[[dict], object]) -> AgentTool:
    """Bind a module-owned handler to one centrally registered tool schema.

    Args:
        name: Name of the tool schema registered in TOOL_CATALOG.
        handler: Feature-module function that performs the tool's behavior.

    Returns:
        A tool that can be passed to a single ReActAgent instance.

    Raises:
        KeyError: If the tool name is not registered in the catalog.
    """
    # Require explicit registration so modules cannot silently invent schemas.
    try:
        definition = TOOL_CATALOG[name]
    except KeyError as error:
        raise KeyError(f"Tool {name!r} is not registered in the tool catalog.") from error

    return AgentTool(
        name=name,
        description=definition["description"],
        parameters=deepcopy(definition["parameters"]),
        handler=handler,
    )
