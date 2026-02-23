"""Azure Pipelines YAML parser.

Parses Azure DevOps YAML pipeline definitions (stages, jobs, steps, templates).
"""

from __future__ import annotations

import logging
from typing import Any

import yaml

from atlas_sdk.enums import EdgeType, NodeType
from atlas_sdk.models.edges import Edge
from atlas_sdk.models.nodes import PipelineNode, JobNode, StageNode, StepNode

from atlas_parser.base import BaseParser, ParseResult

logger = logging.getLogger(__name__)


class AzureYAMLParser(BaseParser):
    """Parses Azure Pipelines YAML definitions."""

    platform = "azure_devops"

    def parse(self, content: str, source_name: str = "") -> ParseResult:
        result = ParseResult()

        try:
            data = yaml.safe_load(content)
        except yaml.YAMLError as e:
            result.errors.append(f"YAML parse error: {e}")
            return result

        if not isinstance(data, dict):
            result.errors.append("Invalid Azure pipeline: not a dict")
            return result

        pipeline = PipelineNode(
            name=source_name or data.get("name", "azure-pipeline"),
            path=source_name,
        )
        result.nodes.append(pipeline)

        # Parse trigger
        trigger = data.get("trigger", [])

        # Parse stages
        stages = data.get("stages", [])
        for i, stage_def in enumerate(stages):
            stage_name = stage_def.get("stage", f"stage-{i}")
            stage = StageNode(
                name=stage_name,
                order=i,
            )
            result.nodes.append(stage)
            result.edges.append(Edge(
                edge_type=EdgeType.CALLS,
                source_node_id=pipeline.id,
                target_node_id=stage.id,
            ))

            # Parse jobs within stage
            jobs = stage_def.get("jobs", [])
            for j, job_def in enumerate(jobs):
                job_name = job_def.get("job", job_def.get("deployment", f"job-{j}"))
                pool = job_def.get("pool", {})
                job = JobNode(
                    name=job_name,
                    metadata={"pool": pool} if pool else {},
                )
                result.nodes.append(job)
                result.edges.append(Edge(
                    edge_type=EdgeType.CALLS,
                    source_node_id=stage.id,
                    target_node_id=job.id,
                ))

                # Parse steps
                steps = job_def.get("steps", [])
                for k, step_def in enumerate(steps):
                    step_name = step_def.get("displayName", step_def.get("script", step_def.get("task", f"step-{k}")))
                    command = step_def.get("script", "")
                    step = StepNode(
                        name=str(step_name)[:80],
                        command=command,
                    )
                    result.nodes.append(step)
                    result.edges.append(Edge(
                        edge_type=EdgeType.CALLS,
                        source_node_id=job.id,
                        target_node_id=step.id,
                    ))

        # If no stages, check for top-level jobs
        if not stages:
            jobs = data.get("jobs", [])
            for j, job_def in enumerate(jobs):
                job_name = job_def.get("job", f"job-{j}")
                job = JobNode(name=job_name)
                result.nodes.append(job)
                result.edges.append(Edge(
                    edge_type=EdgeType.CALLS,
                    source_node_id=pipeline.id,
                    target_node_id=job.id,
                ))

        # If no stages and no jobs, check for top-level steps
        if not stages and not data.get("jobs"):
            steps = data.get("steps", [])
            for k, step_def in enumerate(steps):
                step_name = step_def.get("displayName", step_def.get("script", f"step-{k}"))
                step = StepNode(name=str(step_name)[:80], command=step_def.get("script", ""))
                result.nodes.append(step)
                result.edges.append(Edge(
                    edge_type=EdgeType.CALLS,
                    source_node_id=pipeline.id,
                    target_node_id=step.id,
                ))

        logger.info("Azure parser: %d nodes, %d edges", len(result.nodes), len(result.edges))
        return result
