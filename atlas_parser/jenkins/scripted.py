"""Jenkins Scripted Pipeline parser.

Parses Groovy scripted syntax:
    node('label') {
        stage('Build') { sh 'make build' }
        stage('Test')  { sh 'make test' }
    }

Uses regex matching — no Groovy AST.
"""

from __future__ import annotations

import logging
import re

from atlas_sdk.enums import EdgeType, NodeType, Platform
from atlas_sdk.models.edges import Edge
from atlas_sdk.models.nodes import (
    JobNode,
    PipelineNode,
    SecretRefNode,
    StageNode,
    StepNode,
)

from atlas_parser.base import BaseParser, ParseResult

logger = logging.getLogger(__name__)

_NODE_BLOCK_RE = re.compile(r"node\s*\(\s*['\"]?([^'\")\s]*)['\"]?\s*\)\s*\{", re.MULTILINE)
_STAGE_RE = re.compile(r"stage\s*\(\s*['\"]([^'\"]+)['\"]\s*\)", re.MULTILINE)
_SH_RE = re.compile(r"sh\s+['\"]([^'\"]+)['\"]", re.MULTILINE)
_SH_MULTI_RE = re.compile(r"sh\s+'''(.*?)'''", re.DOTALL)
_BUILD_JOB_RE = re.compile(r"build\s+job:\s*['\"]([^'\"]+)['\"]", re.MULTILINE)
_WITH_CRED_RE = re.compile(r"withCredentials\s*\([^)]*credentialsId:\s*['\"]([^'\"]+)['\"]", re.MULTILINE)
_CHECKOUT_RE = re.compile(r"checkout\s+scm", re.MULTILINE)
_DOCKER_IMAGE_RE = re.compile(r"docker\.image\s*\(\s*['\"]([^'\"]+)['\"]\s*\)", re.MULTILINE)


class ScriptedParser(BaseParser):
    """Parser for Jenkins Scripted Pipeline syntax."""

    def parse(self, content: str, source_name: str = "") -> ParseResult:
        result = ParseResult()

        # Detect node block
        node_match = _NODE_BLOCK_RE.search(content)
        agent_label = node_match.group(1) if node_match else None

        # Pipeline node
        pipeline = PipelineNode(
            name=source_name or "scripted-pipeline",
            platform=Platform.JENKINS,
            path=source_name,
            agent=agent_label or None,
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
            result.edges.append(Edge(
                edge_type=EdgeType.CALLS,
                source_node_id=pipeline.id,
                target_node_id=stage.id,
            ))
            if prev_stage:
                result.edges.append(Edge(
                    edge_type=EdgeType.TRIGGERS,
                    source_node_id=prev_stage.id,
                    target_node_id=stage.id,
                ))
            prev_stage = stage

        # Extract sh steps
        for cmd in _SH_RE.findall(content):
            step = StepNode(
                name=f"sh: {cmd[:50]}",
                platform=Platform.JENKINS,
                command=cmd,
                shell="sh",
            )
            result.nodes.append(step)

        # Extract multi-line sh steps
        for cmd in _SH_MULTI_RE.findall(content):
            first_line = cmd.strip().split("\n")[0][:50]
            step = StepNode(
                name=f"sh: {first_line}",
                platform=Platform.JENKINS,
                command=cmd.strip(),
                shell="sh",
            )
            result.nodes.append(step)

        # Extract downstream build triggers
        for job_name in _BUILD_JOB_RE.findall(content):
            job = JobNode(name=job_name, platform=Platform.JENKINS)
            result.nodes.append(job)
            result.edges.append(Edge(
                edge_type=EdgeType.TRIGGERS,
                source_node_id=pipeline.id,
                target_node_id=job.id,
            ))

        # Extract credential references
        for cred_id in _WITH_CRED_RE.findall(content):
            secret = SecretRefNode(
                name=cred_id,
                key=cred_id,
                platform=Platform.JENKINS,
            )
            result.nodes.append(secret)

        logger.info(
            "Parsed scripted pipeline %s: %d nodes, %d edges",
            source_name, len(result.nodes), len(result.edges),
        )
        return result
