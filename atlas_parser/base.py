"""Abstract parser base class and shared result type.

All platform-specific parsers implement BaseParser.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from atlas_sdk.models.edges import Edge
from atlas_sdk.models.nodes import Node


@dataclass
class ParseResult:
    """Result of parsing a single pipeline configuration."""

    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def merge(self, other: ParseResult) -> None:
        """Merge another result into this one."""
        self.nodes.extend(other.nodes)
        self.edges.extend(other.edges)
        self.errors.extend(other.errors)


class BaseParser(ABC):
    """Abstract parser — one per CI/CD config format."""

    @abstractmethod
    def parse(self, content: str, source_name: str = "") -> ParseResult:
        """Parse raw config content into graph nodes and edges.

        Args:
            content: Raw pipeline config (YAML, Groovy, XML).
            source_name: Job/project name for context.

        Returns:
            ParseResult with extracted nodes and edges.
        """
