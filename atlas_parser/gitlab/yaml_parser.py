"""GitLab CI YAML parser.

Parses .gitlab-ci.yml into graph nodes and edges.
Handles: stages, jobs, scripts, services, artifacts, needs, dependencies.
"""

from __future__ import annotations

import logging

import yaml

from atlas_sdk.enums import EdgeType, Platform
from atlas_sdk.models.edges import Edge
from atlas_sdk.models.nodes import (
    ArtifactNode,
    ContainerImageNode,
    EnvironmentNode,
    ExternalServiceNode,
    PipelineNode,
    SecretRefNode,
    StageNode,
    StepNode,
)

from atlas_parser.base import BaseParser, ParseResult

logger = logging.getLogger(__name__)

# Top-level keys that are NOT job definitions
_RESERVED_KEYS = {
    "stages", "variables", "image", "services", "before_script",
    "after_script", "cache", "default", "include", "workflow",
    "pages",
}


class GitLabYAMLParser(BaseParser):
    """Parser for .gitlab-ci.yml files."""

    def parse(self, content: str, source_name: str = "") -> ParseResult:
        result = ParseResult()

        try:
            data = yaml.safe_load(content)
        except yaml.YAMLError as e:
            result.errors.append(f"Invalid YAML in {source_name}: {e}")
            return result

        if not isinstance(data, dict):
            result.errors.append(f"Expected dict at top level in {source_name}")
            return result

        # Pipeline node
        pipeline = PipelineNode(
            name=source_name or ".gitlab-ci.yml",
            platform=Platform.GITLAB,
            path=source_name,
        )
        result.nodes.append(pipeline)

        # Global image
        global_image = data.get("image")
        if isinstance(global_image, str) and global_image:
            img = ContainerImageNode(
                name=global_image,
                platform=Platform.GITLAB,
                tag=global_image.split(":")[-1] if ":" in global_image else "latest",
            )
            result.nodes.append(img)

        # Stages
        stage_names = data.get("stages", [])
        stage_nodes: dict[str, StageNode] = {}
        prev_stage = None
        for i, stage_name in enumerate(stage_names):
            stage = StageNode(
                name=stage_name,
                platform=Platform.GITLAB,
                order=i,
            )
            stage_nodes[stage_name] = stage
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

        # Global variables (detect secrets)
        variables = data.get("variables", {})
        if isinstance(variables, dict):
            for var_name, var_val in variables.items():
                # Variables can be dicts with value/description
                val = var_val if isinstance(var_val, str) else ""
                if any(kw in var_name.upper() for kw in ("SECRET", "TOKEN", "PASSWORD", "KEY")):
                    secret = SecretRefNode(
                        name=var_name,
                        key=var_name,
                        platform=Platform.GITLAB,
                    )
                    result.nodes.append(secret)

        # Parse jobs (anything not in reserved keys and not starting with .)
        for key, job_def in data.items():
            if key in _RESERVED_KEYS or key.startswith(".") or not isinstance(job_def, dict):
                continue
            self._parse_job(key, job_def, pipeline, stage_nodes, result)

        logger.info(
            "Parsed GitLab CI %s: %d nodes, %d edges",
            source_name, len(result.nodes), len(result.edges),
        )
        return result

    def _parse_job(
        self,
        job_name: str,
        job_def: dict,
        pipeline: PipelineNode,
        stage_nodes: dict[str, StageNode],
        result: ParseResult,
    ) -> None:
        """Parse a single GitLab CI job definition."""

        # Step node for the job
        scripts = job_def.get("script", [])
        if isinstance(scripts, str):
            scripts = [scripts]

        cmd = "; ".join(scripts) if scripts else ""
        step = StepNode(
            name=job_name,
            platform=Platform.GITLAB,
            command=cmd[:500] if cmd else None,
        )
        result.nodes.append(step)

        # Link job to its stage
        stage_name = job_def.get("stage", "test")
        if stage_name in stage_nodes:
            result.edges.append(Edge(
                edge_type=EdgeType.CALLS,
                source_node_id=stage_nodes[stage_name].id,
                target_node_id=step.id,
            ))
        else:
            # Stage not in explicit list — link to pipeline
            result.edges.append(Edge(
                edge_type=EdgeType.CALLS,
                source_node_id=pipeline.id,
                target_node_id=step.id,
            ))

        # Job image
        image = job_def.get("image")
        if isinstance(image, str) and image:
            img = ContainerImageNode(
                name=image,
                platform=Platform.GITLAB,
                tag=image.split(":")[-1] if ":" in image else "latest",
            )
            result.nodes.append(img)
            result.edges.append(Edge(
                edge_type=EdgeType.DEPENDS_ON,
                source_node_id=step.id,
                target_node_id=img.id,
            ))

        # Services (e.g. postgres, redis)
        services = job_def.get("services", [])
        for svc in services:
            svc_name = svc if isinstance(svc, str) else svc.get("name", "") if isinstance(svc, dict) else ""
            if svc_name:
                svc_node = ExternalServiceNode(
                    name=svc_name,
                    platform=Platform.GITLAB,
                    service_type="ci_service",
                )
                result.nodes.append(svc_node)

        # Artifacts
        artifacts = job_def.get("artifacts", {})
        if isinstance(artifacts, dict):
            paths = artifacts.get("paths", [])
            for path in paths:
                art = ArtifactNode(
                    name=f"{job_name}:{path}",
                    platform=Platform.GITLAB,
                    path=path,
                )
                result.nodes.append(art)
                result.edges.append(Edge(
                    edge_type=EdgeType.PRODUCES,
                    source_node_id=step.id,
                    target_node_id=art.id,
                ))

        # Needs (DAG dependencies)
        needs = job_def.get("needs", [])
        if isinstance(needs, list):
            for need in needs:
                need_name = need if isinstance(need, str) else need.get("job", "") if isinstance(need, dict) else ""
                if need_name:
                    step.metadata.setdefault("needs", []).append(need_name)

        # Environment
        env = job_def.get("environment", {})
        if env:
            env_name = env if isinstance(env, str) else env.get("name", "") if isinstance(env, dict) else ""
            if env_name:
                env_node = EnvironmentNode(
                    name=env_name,
                    platform=Platform.GITLAB,
                )
                result.nodes.append(env_node)
                result.edges.append(Edge(
                    edge_type=EdgeType.DEPLOYS_TO,
                    source_node_id=step.id,
                    target_node_id=env_node.id,
                ))
