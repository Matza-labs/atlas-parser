"""Bitbucket Pipelines YAML parser.

Parses bitbucket-pipelines.yml definitions (pipelines, steps, caches).
"""

from __future__ import annotations

import logging
from typing import Any

import yaml

from atlas_sdk.enums import EdgeType, NodeType
from atlas_sdk.models.edges import Edge
from atlas_sdk.models.nodes import PipelineNode, StageNode, StepNode

from atlas_parser.base import BaseParser, ParseResult

logger = logging.getLogger(__name__)


class BitbucketYAMLParser(BaseParser):
    """Parses Bitbucket Pipelines YAML definitions."""

    platform = "bitbucket"

    def parse(self, content: str, source_name: str = "") -> ParseResult:
        result = ParseResult()

        try:
            data = yaml.safe_load(content)
        except yaml.YAMLError as e:
            result.errors.append(f"YAML parse error: {e}")
            return result

        if not isinstance(data, dict):
            result.errors.append("Invalid Bitbucket pipeline: not a dict")
            return result

        pipeline = PipelineNode(
            name=source_name or "bitbucket-pipeline",
            path="bitbucket-pipelines.yml",
        )
        result.nodes.append(pipeline)

        pipelines = data.get("pipelines", {})

        # Parse default pipeline
        default = pipelines.get("default", [])
        self._parse_steps(result, pipeline, default, "default")

        # Parse branches
        branches = pipelines.get("branches", {})
        for branch_name, steps_list in branches.items():
            stage = StageNode(name=f"branch:{branch_name}")
            result.nodes.append(stage)
            result.edges.append(Edge(
                edge_type=EdgeType.CALLS,
                source_node_id=pipeline.id,
                target_node_id=stage.id,
            ))
            self._parse_steps(result, stage, steps_list, branch_name)

        # Parse pull-requests
        prs = pipelines.get("pull-requests", {})
        for pr_pattern, steps_list in prs.items():
            stage = StageNode(name=f"pr:{pr_pattern}")
            result.nodes.append(stage)
            result.edges.append(Edge(
                edge_type=EdgeType.CALLS,
                source_node_id=pipeline.id,
                target_node_id=stage.id,
            ))
            self._parse_steps(result, stage, steps_list, f"pr-{pr_pattern}")

        logger.info("Bitbucket parser: %d nodes, %d edges", len(result.nodes), len(result.edges))
        return result

    def _parse_steps(self, result: ParseResult, parent, steps_list: list, context: str) -> None:
        """Parse a list of step definitions."""
        if not isinstance(steps_list, list):
            return

        for i, step_wrapper in enumerate(steps_list):
            if not isinstance(step_wrapper, dict):
                continue
            step_def = step_wrapper.get("step", {})
            if not step_def:
                continue

            step_name = step_def.get("name", f"{context}-step-{i}")
            scripts = step_def.get("script", [])
            command = "\n".join(scripts) if isinstance(scripts, list) else str(scripts)

            step = StepNode(
                name=step_name,
                command=command[:200],
            )
            result.nodes.append(step)
            result.edges.append(Edge(
                edge_type=EdgeType.CALLS,
                source_node_id=parent.id,
                target_node_id=step.id,
            ))
