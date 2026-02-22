"""Jenkins Declarative Pipeline parser.

Parses Groovy declarative syntax:
    pipeline {
        agent any
        stages {
            stage('Build') { steps { sh 'make build' } }
            stage('Test')  { steps { sh 'make test' } }
        }
        post { ... }
    }

Uses regex-based extraction — no Groovy AST.
"""

from __future__ import annotations

import logging
import re

from atlas_sdk.enums import EdgeType, NodeType, Platform
from atlas_sdk.models.edges import Edge
from atlas_sdk.models.nodes import (
    EnvironmentNode,
    JobNode,
    PipelineNode,
    SecretRefNode,
    StageNode,
    StepNode,
)

from atlas_parser.base import BaseParser, ParseResult

logger = logging.getLogger(__name__)

# Regex patterns for declarative pipeline elements
_PIPELINE_RE = re.compile(r"pipeline\s*\{", re.MULTILINE)
_AGENT_RE = re.compile(r"agent\s+(\{[^}]*\}|any|none|\w+)", re.MULTILINE)
_STAGE_RE = re.compile(r"stage\s*\(\s*['\"]([^'\"]+)['\"]\s*\)", re.MULTILINE)
_SH_STEP_RE = re.compile(r"sh\s+['\"]([^'\"]+)['\"]", re.MULTILINE)
_SCRIPT_STEP_RE = re.compile(r"script\s*\{", re.MULTILINE)
_PARALLEL_RE = re.compile(r"parallel\s*\{", re.MULTILINE)
_WHEN_RE = re.compile(r"when\s*\{([^}]*)\}", re.MULTILINE)
_TIMEOUT_RE = re.compile(r"timeout\s*\(\s*time:\s*(\d+)", re.MULTILINE)
_TRIGGER_RE = re.compile(r"triggers\s*\{([^}]*)\}", re.MULTILINE)
_PARAM_RE = re.compile(r"parameters\s*\{([^}]*)\}", re.MULTILINE)
_ENV_RE = re.compile(r"environment\s*\{([^}]*)\}", re.MULTILINE)
_CRED_RE = re.compile(r"credentials\s*\(\s*['\"]([^'\"]+)['\"]\s*\)", re.MULTILINE)
_BUILD_JOB_RE = re.compile(r"build\s+job:\s*['\"]([^'\"]+)['\"]", re.MULTILINE)
_DOCKER_RE = re.compile(r"docker\s*\{[^}]*image\s+['\"]([^'\"]+)['\"]", re.MULTILINE | re.DOTALL)
_DOCKER_SIMPLE_RE = re.compile(r"agent\s*\{\s*docker\s+['\"]([^'\"]+)['\"]", re.MULTILINE)


class DeclarativeParser(BaseParser):
    """Parser for Jenkins Declarative Pipeline syntax."""

    def parse(self, content: str, source_name: str = "") -> ParseResult:
        result = ParseResult()

        if not _PIPELINE_RE.search(content):
            result.errors.append(f"No 'pipeline {{' block found in {source_name}")
            return result

        # Pipeline node
        agent = self._extract_agent(content)
        pipeline = PipelineNode(
            name=source_name or "pipeline",
            platform=Platform.JENKINS,
            path=source_name,
            agent=agent,
        )
        result.nodes.append(pipeline)

        # Extract stages
        stages = _STAGE_RE.findall(content)
        prev_stage = None
        for i, stage_name in enumerate(stages):
            stage = StageNode(
                name=stage_name,
                platform=Platform.JENKINS,
                order=i,
            )
            result.nodes.append(stage)

            # Pipeline → Stage edge
            result.edges.append(Edge(
                edge_type=EdgeType.CALLS,
                source_node_id=pipeline.id,
                target_node_id=stage.id,
            ))

            # Stage → Stage sequential edge
            if prev_stage:
                result.edges.append(Edge(
                    edge_type=EdgeType.TRIGGERS,
                    source_node_id=prev_stage.id,
                    target_node_id=stage.id,
                ))
            prev_stage = stage

        # Extract sh steps
        steps = _SH_STEP_RE.findall(content)
        for cmd in steps:
            step = StepNode(
                name=f"sh: {cmd[:50]}",
                platform=Platform.JENKINS,
                command=cmd,
                shell="sh",
            )
            result.nodes.append(step)

        # Extract downstream build triggers
        downstream_jobs = _BUILD_JOB_RE.findall(content)
        for job_name in downstream_jobs:
            job = JobNode(
                name=job_name,
                platform=Platform.JENKINS,
            )
            result.nodes.append(job)
            result.edges.append(Edge(
                edge_type=EdgeType.TRIGGERS,
                source_node_id=pipeline.id,
                target_node_id=job.id,
            ))

        # Extract credential references
        creds = _CRED_RE.findall(content)
        for cred_id in creds:
            secret = SecretRefNode(
                name=cred_id,
                key=cred_id,
                platform=Platform.JENKINS,
            )
            result.nodes.append(secret)

        # Extract environment variables
        env_match = _ENV_RE.search(content)
        if env_match:
            env_block = env_match.group(1)
            env_vars = re.findall(r"(\w+)\s*=", env_block)
            if env_vars:
                env_node = EnvironmentNode(
                    name="pipeline-env",
                    platform=Platform.JENKINS,
                    metadata={"variables": env_vars},
                )
                result.nodes.append(env_node)

        # Extract timeout
        timeout_match = _TIMEOUT_RE.search(content)
        if timeout_match:
            pipeline.metadata["timeout_minutes"] = int(timeout_match.group(1))

        logger.info(
            "Parsed declarative pipeline %s: %d nodes, %d edges",
            source_name, len(result.nodes), len(result.edges),
        )
        return result

    @staticmethod
    def _extract_agent(content: str) -> str | None:
        match = _AGENT_RE.search(content)
        if match:
            agent = match.group(1).strip()
            return agent if agent not in ("none", "{") else None
        return None
