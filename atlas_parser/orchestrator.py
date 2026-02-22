"""Parser orchestrator — routes configs to correct parsers.

Receives ScanResultEvent data, detects the format of each pipeline
config, dispatches to the right parser, and aggregates results.
"""

from __future__ import annotations

import logging
from typing import Any

from atlas_sdk.enums import Platform
from atlas_sdk.models.edges import Edge
from atlas_sdk.models.nodes import Node

from atlas_parser.base import ParseResult
from atlas_parser.gitlab.include_resolver import resolve_extends
from atlas_parser.gitlab.yaml_parser import GitLabYAMLParser
from atlas_parser.jenkins.declarative import DeclarativeParser
from atlas_parser.jenkins.freestyle import FreestyleParser
from atlas_parser.jenkins.scripted import ScriptedParser
from atlas_parser.github.yaml_parser import GitHubYAMLParser

logger = logging.getLogger(__name__)


class ParserOrchestrator:
    """Routes pipeline configs to the correct parser and aggregates results."""

    def __init__(self) -> None:
        self._declarative = DeclarativeParser()
        self._scripted = ScriptedParser()
        self._freestyle = FreestyleParser()
        self._gitlab = GitLabYAMLParser()
        self._github = GitHubYAMLParser()

    def parse_all(
        self,
        pipeline_configs: list[dict[str, Any]],
    ) -> ParseResult:
        """Parse all pipeline configs from a scan result.

        Args:
            pipeline_configs: List of dicts with keys:
                job_name, path, content, job_type, platform metadata.

        Returns:
            Aggregated ParseResult with all nodes and edges.
        """
        combined = ParseResult()

        for config in pipeline_configs:
            content = config.get("content", "")
            job_name = config.get("job_name", "")
            job_type = config.get("job_type", "")
            platform = config.get("platform", "")

            if not content:
                combined.errors.append(f"Empty content for {job_name}")
                continue

            try:
                result = self._route_and_parse(content, job_name, job_type, platform)
                combined.merge(result)
            except Exception as e:
                combined.errors.append(f"Error parsing {job_name}: {e}")
                logger.exception("Failed to parse %s", job_name)

        logger.info(
            "Orchestrator complete: %d nodes, %d edges, %d errors",
            len(combined.nodes), len(combined.edges), len(combined.errors),
        )
        return combined

    def _route_and_parse(
        self,
        content: str,
        job_name: str,
        job_type: str,
        platform: str,
    ) -> ParseResult:
        """Route a single config to the correct parser."""

        # GitHub Actions
        if platform == Platform.GITHUB_ACTIONS or job_type == "github_actions":
            return self._github.parse(content, source_name=job_name)

        # GitLab
        if platform == Platform.GITLAB or job_type == "gitlab_ci":
            data = resolve_extends(
                __import__("yaml").safe_load(content) or {}
            )
            resolved_content = __import__("yaml").dump(data)
            return self._gitlab.parse(resolved_content, source_name=job_name)

        # Jenkins — detect format
        if job_type == "freestyle" or content.strip().startswith("<"):
            return self._freestyle.parse(content, source_name=job_name)

        if "pipeline {" in content or "pipeline{" in content:
            return self._declarative.parse(content, source_name=job_name)

        if "node(" in content or "node " in content or "stage(" in content:
            return self._scripted.parse(content, source_name=job_name)

        # Fallback: try declarative first, then scripted
        result = self._declarative.parse(content, source_name=job_name)
        if result.errors:
            return self._scripted.parse(content, source_name=job_name)
        return result
