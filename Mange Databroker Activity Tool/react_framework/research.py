"""Provider-neutral types for future compliant public-source research."""

from typing import Protocol, TypedDict


class PublicSource(TypedDict):
    """Describe one public search result and its attributable snippet."""

    title: str
    url: str
    publisher: str
    snippet: str
    accessed_at: str


class PublicSearchProvider(Protocol):
    """Define a provider adapter that complies with its service's terms.

    Implementations must use an approved public-search interface, submit only
    the explicitly approved query, and return attributable public results.
    They must not receive case files or personal identifiers.
    """

    def search_public(self, query: str, limit: int) -> list[PublicSource]:
        """Search public sources under the provider's permitted terms of use."""
        ...
