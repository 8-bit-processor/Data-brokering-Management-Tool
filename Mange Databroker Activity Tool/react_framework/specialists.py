"""Create isolated local Ollama specialists for research, architecture, and law."""

import re
from collections.abc import Iterable
from typing import Callable

from react_framework.agent import ActivityCallback, AgentTool, ReActAgent
from react_framework.research import PublicSearchProvider
from react_framework.tool_catalog import bind_tool


# These specialist agents intentionally have no internet or filesystem tools.
RESEARCH_INSTRUCTIONS = """
You are a research-planning specialist for public information.
Live web search is not configured. Do not claim that you searched the internet,
consulted a source, or verified a fact. Help turn the user's request into a
neutral, non-identifying search plan, and identify appropriate public primary
or official sources to consult. Do not include personal identifiers in any
proposed search query. Clearly label the output as a plan, not research results.
"""

RESEARCH_WITH_SEARCH_INSTRUCTIONS = """
You are a public-source research specialist. Use search_public_sources for
research; do not answer factual questions from memory as if verified. Queries
must be non-identifying and limited to publicly accessible sources. Cite each
finding with the exact title, publisher, URL, snippet, and access date returned
by the search tool. Clearly distinguish source content from your summary.
"""

ARCHITECT_INSTRUCTIONS = """
You are a software architecture specialist. Give concise, modular design
analysis for the specific task provided. Do not assume access to files, tools,
or implementation details that were not included in the task. Identify
assumptions and trade-offs rather than silently choosing product requirements.
"""

LEGAL_INSTRUCTIONS = """
You are a local preliminary legal-issue-spotting specialist, not the user's
attorney. Analyze only the question, jurisdiction, and local case context
provided. No live legal research tools or verified source library are
configured, so do not invent citations, quote laws from memory as verified, or
claim that a legal violation or damages amount is established. Distinguish
provided facts from allegations and analysis, identify uncertainties, and
prepare questions for a qualified professional attorney to review.
"""

# Reject common personal-identifier formats before accepting a public-query
# planning request. This is a guardrail, not a complete identity detector.
_EMAIL_PATTERN = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
_US_SSN_PATTERN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_US_PHONE_PATTERN = re.compile(
    r"(?<!\d)(?:\+?1[\s.-]?)?(?:\(?\d{3}\)?[\s.-]?)\d{3}[\s.-]?\d{4}(?!\d)"
)


def _validate_public_research_query(query: str) -> None:
    """Reject obvious personal identifiers from a proposed public search query."""
    if not query.strip() or len(query) > 2_000:
        raise ValueError("Research query must contain 1 to 2000 characters.")
    if (
        _EMAIL_PATTERN.search(query)
        or _US_SSN_PATTERN.search(query)
        or _US_PHONE_PATTERN.search(query)
    ):
        raise ValueError(
            "The research query appears to contain a personal identifier. "
            "Use a general, non-identifying query."
        )


def create_specialist_tools(
    activity_callback: ActivityCallback | None = None,
    research_provider: PublicSearchProvider | None = None,
    search_approval: Callable[[str], bool] | None = None,
    selected_names: Iterable[str] = (
        "invoke_research_agent",
        "invoke_architect_agent",
        "invoke_legal_agent",
    ),
) -> tuple[AgentTool, ...]:
    """Bind selected specialist schemas to isolated local Ollama agents.

    Args:
        activity_callback: Receiver for each specialist's visible activity.
        selected_names: Central catalog names to expose to the caller.

    Raises:
        ValueError: If a live provider is configured without a query-approval
            callback.
    """
    if research_provider is not None and search_approval is None:
        raise ValueError("Live research requires a user-facing query approval callback.")


    def run_research(arguments: dict) -> dict:
        """Research through a configured provider, or make a plan only."""
        query = arguments["query"]
        _validate_public_research_query(query)
        if research_provider is None:
            research_agent = ReActAgent(
                instructions=RESEARCH_INSTRUCTIONS,
                agent_name="Research specialist",
                activity_callback=activity_callback,
            )
            result = research_agent.run(
                "Prepare a public-source research plan for this non-identifying query: "
                f"{query}"
            )
            return {
                "status": "planning_only",
                "live_web_search_configured": False,
                "plan": result.content,
            }

        # The provider receives only this query and cannot access case files.
        def search_public_sources(search_arguments: dict) -> dict:
            """Request user approval before sending a query to the provider."""
            public_query = search_arguments["query"]
            _validate_public_research_query(public_query)
            if not search_approval(public_query):
                return {"status": "cancelled", "sources": []}
            return _search_public_sources(
                research_provider,
                public_query,
                search_arguments["limit"],
            )

        search_tool = bind_tool("search_public_sources", search_public_sources)
        research_agent = ReActAgent(
            instructions=RESEARCH_WITH_SEARCH_INSTRUCTIONS,
            tools=(search_tool,),
            agent_name="Research specialist",
            activity_callback=activity_callback,
        )
        result = research_agent.run(
            "Prepare a public-source research plan for this non-identifying query: "
            f"{query}"
        )
        sources = [
            source
            for tool_result in result.tool_results
            if tool_result.name == "search_public_sources"
            and isinstance(tool_result.output, dict)
            for source in tool_result.output.get("sources", [])
        ]
        return {
            "status": "researched" if sources else "no_sources_returned",
            "findings": result.content,
            "sources": sources,
        }

    def run_architecture(arguments: dict) -> dict:
        """Ask the independent local architecture specialist to review a task."""
        task = arguments["task"]
        if not task.strip() or len(task) > 20_000:
            raise ValueError("Architecture task must contain 1 to 20000 characters.")
        architect_agent = ReActAgent(
            instructions=ARCHITECT_INSTRUCTIONS,
            agent_name="Architecture specialist",
            activity_callback=activity_callback,
        )
        result = architect_agent.run(task)
        return {"status": "complete", "analysis": result.content}

    def run_legal(arguments: dict) -> dict:
        """Ask the local legal specialist to issue-spot supplied case material."""
        question = arguments["question"]
        jurisdiction = arguments["jurisdiction"]
        case_context = arguments["case_context"]
        if not question.strip() or len(question) > 10_000:
            raise ValueError("Legal question must contain 1 to 10000 characters.")
        if not jurisdiction.strip() or len(jurisdiction) > 500:
            raise ValueError("Jurisdiction must contain 1 to 500 characters.")
        if len(case_context) > 30_000:
            raise ValueError("Local case context must not exceed 30000 characters.")

        legal_agent = ReActAgent(
            instructions=LEGAL_INSTRUCTIONS,
            agent_name="Legal issue-spotting specialist",
            activity_callback=activity_callback,
        )
        result = legal_agent.run(
            f"Jurisdiction: {jurisdiction}\n\n"
            f"Question: {question}\n\n"
            f"User-provided local case context:\n{case_context}"
        )
        return {
            "status": "preliminary_local_analysis",
            "live_legal_research_configured": False,
            "sources": [],
            "analysis": result.content,
        }

    # Keep invocation handlers in a registry so callers can select a subset.
    available_handlers = {
        "invoke_research_agent": run_research,
        "invoke_architect_agent": run_architecture,
        "invoke_legal_agent": run_legal,
    }
    selected_tools = []
    for name in selected_names:
        if name not in available_handlers:
            raise ValueError(f"Unknown specialist tool: {name!r}.")
        selected_tools.append(bind_tool(name, available_handlers[name]))
    return tuple(selected_tools)


def _search_public_sources(
    provider: PublicSearchProvider,
    query: str,
    limit: int,
) -> dict:
    """Validate a public query and normalize results from the configured API."""
    _validate_public_research_query(query)
    if not 1 <= limit <= 10:
        raise ValueError("Public search limit must be between 1 and 10.")

    sources = provider.search_public(query, limit)
    if not isinstance(sources, list):
        raise RuntimeError("Public search provider returned an invalid result list.")
    validated_sources = []
    for source in sources[:limit]:
        if not isinstance(source, dict):
            raise RuntimeError("Public search provider returned an invalid source.")
        if not isinstance(source.get("url"), str) or not source["url"].startswith("https://"):
            raise RuntimeError("Public search sources must have HTTPS URLs.")
        if any(
            not isinstance(source.get(field), str)
            for field in ("title", "publisher", "snippet", "accessed_at")
        ):
            raise RuntimeError("Public search sources must include attribution fields.")
        validated_sources.append(source)
    return {"sources": validated_sources}
