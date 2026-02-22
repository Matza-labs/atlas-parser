"""GitHub Actions YAML parser.

Parses .github/workflows/*.yml files into a unified CI/CD Graph structure.
Extracts pipelines, jobs, steps, environment dependencies, and secrets.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import yaml

from atlas_sdk.enums import EdgeType, Platform
from atlas_sdk.models.edges import Edge
from atlas_sdk.models.nodes import (
    EnvironmentNode,
    JobNode,
    PipelineNode,
    SecretRefNode,
    StepNode,
)

from atlas_parser.base import BaseParser, ParseResult

logger = logging.getLogger(__name__)

# Basic regex for extracting secrets from GitHub Actions syntax: ${{ secrets.FOO }}
SECRET_REGEX = re.compile(r"\${{\s*secrets\.([\w_]+)\s*}}")


class GitHubYAMLParser(BaseParser):
    """Parser for GitHub Actions YAML workflows."""

    def parse(self, content: str, source_name: str = "") -> ParseResult:
        result = ParseResult()

        try:
            workflow: dict[str, Any] = yaml.safe_load(content) or {}
        except yaml.YAMLError as e:
            result.errors.append(f"Invalid YAML in {source_name}: {e}")
            logger.debug("YAML parse error: %s", e)
            return result

        if not isinstance(workflow, dict):
            result.errors.append(f"Root must be a dict in {source_name}")
            return result

        workflow_name = workflow.get("name", source_name or "Unknown Workflow")
        pipeline = PipelineNode(name=workflow_name, platform=Platform.GITHUB_ACTIONS)
        result.nodes.append(pipeline)

        jobs_dict = workflow.get("jobs", {})
        if not isinstance(jobs_dict, dict):
            result.errors.append(f"Jobs must be a dictionary in {source_name}")
            return result

        job_nodes: dict[str, JobNode] = {}

        for job_id, job_config in jobs_dict.items():
            if not isinstance(job_config, dict):
                continue
                
            job_name = job_config.get("name", job_id)
            runs_on = job_config.get("runs-on", "unknown")
            if isinstance(runs_on, list):
                runs_on_str = ",".join(str(r) for r in runs_on)
            else:
                runs_on_str = str(runs_on)

            job = JobNode(
                name=f"{workflow_name}::{job_name}", 
                parameters={"agent_label": runs_on_str},
            )
            job_nodes[job_id] = job
            result.nodes.append(job)

            # Link Pipeline -> Job
            result.edges.append(
                Edge(
                    edge_type=EdgeType.CALLS,
                    source_node_id=pipeline.id,
                    target_node_id=job.id,
                )
            )

            # Environment
            if isinstance(job_config.get("environment"), str):
                env_node = EnvironmentNode(name=job_config["environment"])
                result.nodes.append(env_node)
                result.edges.append(
                    Edge(
                        edge_type=EdgeType.DEPLOYS_TO,
                        source_node_id=job.id,
                        target_node_id=env_node.id,
                    )
                )
            elif isinstance(job_config.get("environment"), dict):
                env_name = job_config["environment"].get("name", "unknown")
                env_node = EnvironmentNode(name=env_name)
                result.nodes.append(env_node)
                result.edges.append(
                    Edge(
                        edge_type=EdgeType.DEPLOYS_TO,
                        source_node_id=job.id,
                        target_node_id=env_node.id,
                    )
                )

            # Discover Secrets in job-level env
            self._extract_secrets(job_config.get("env", {}), job.id, result)

            # Parse Steps
            steps = job_config.get("steps", [])
            if isinstance(steps, list):
                for i, step_config in enumerate(steps, 1):
                    if not isinstance(step_config, dict):
                        continue

                    step_name = step_config.get("name", f"Step {i}")
                    uses = step_config.get("uses")
                    run = step_config.get("run")

                    # Handle Action usage vs Shell script
                    if uses:
                        command = f"uses: {uses}"
                        shell = "action"
                    elif run:
                        command = run
                        shell = step_config.get("shell", "default")
                    else:
                        command = ""
                        shell = ""

                    step_node = StepNode(
                        name=f"{job.name} / {step_name}",
                        command=command,
                        shell=shell,
                    )
                    result.nodes.append(step_node)
                    result.edges.append(
                        Edge(
                            edge_type=EdgeType.CALLS,
                            source_node_id=job.id,
                            target_node_id=step_node.id,
                        )
                    )

                    # Discover Secrets in step-level fields
                    self._extract_secrets(step_config, step_node.id, result)

        # Handle explicit Job dependencies (`needs`)
        for job_id, job_config in jobs_dict.items():
            if not isinstance(job_config, dict) or "needs" not in job_config:
                continue
                
            needs = job_config["needs"]
            if isinstance(needs, str):
                needs = [needs]
                
            job_node = job_nodes.get(job_id)
            if not job_node or not isinstance(needs, list):
                continue

            for needed_job_id in needs:
                needed_job_node = job_nodes.get(needed_job_id)
                if needed_job_node:
                    # Job -> DEPENDS_ON -> NeededJob
                    result.edges.append(
                        Edge(
                            edge_type=EdgeType.DEPENDS_ON,
                            source_node_id=job_node.id,
                            target_node_id=needed_job_node.id,
                        )
                    )

        return result

    def _extract_secrets(
        self, data: Any, calling_node_id: str, result: ParseResult
    ) -> None:
        """Recursively search for secrets in dicts/strings and link to node."""
        if isinstance(data, dict):
            for k, v in data.items():
                self._extract_secrets(v, calling_node_id, result)
        elif isinstance(data, list):
            for item in data:
                self._extract_secrets(item, calling_node_id, result)
        elif isinstance(data, str):
            matches = SECRET_REGEX.findall(data)
            for match in matches:
                secret_node = SecretRefNode(name=f"secret:{match}", key=match)
                result.nodes.append(secret_node)
                result.edges.append(
                    Edge(
                        edge_type=EdgeType.CONSUMES,
                        source_node_id=calling_node_id,
                        target_node_id=secret_node.id,
                    )
                )
