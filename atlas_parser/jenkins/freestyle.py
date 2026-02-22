"""Jenkins Freestyle job XML parser.

Parses Jenkins config.xml for freestyle jobs using lxml/xml.etree.
Extracts builders, publishers, SCM config, and downstream triggers.
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET

from atlas_sdk.enums import EdgeType, Platform
from atlas_sdk.models.edges import Edge
from atlas_sdk.models.nodes import (
    JobNode,
    PipelineNode,
    RepositoryNode,
    SecretRefNode,
    StepNode,
)

from atlas_parser.base import BaseParser, ParseResult

logger = logging.getLogger(__name__)


class FreestyleParser(BaseParser):
    """Parser for Jenkins Freestyle job config.xml."""

    def parse(self, content: str, source_name: str = "") -> ParseResult:
        result = ParseResult()

        try:
            root = ET.fromstring(content)
        except ET.ParseError as e:
            result.errors.append(f"Invalid XML in {source_name}: {e}")
            return result

        # Pipeline/Job node
        job = PipelineNode(
            name=source_name or "freestyle-job",
            platform=Platform.JENKINS,
            path=source_name,
            metadata={"job_type": "freestyle"},
        )
        result.nodes.append(job)

        # Extract SCM (Git)
        for scm in root.iter("scm"):
            for url_elem in scm.iter("url"):
                if url_elem.text:
                    repo = RepositoryNode(
                        name=url_elem.text.split("/")[-1].replace(".git", ""),
                        url=url_elem.text,
                        platform=Platform.JENKINS,
                    )
                    result.nodes.append(repo)
                    result.edges.append(Edge(
                        edge_type=EdgeType.DEPENDS_ON,
                        source_node_id=job.id,
                        target_node_id=repo.id,
                    ))

            # Extract branches
            for branch_elem in scm.iter("name"):
                if branch_elem.text:
                    job.metadata.setdefault("branches", []).append(branch_elem.text)

        # Extract builders (Shell, Maven, Batch, etc.)
        for builders in root.iter("builders"):
            for shell in builders.iter("hudson.tasks.Shell"):
                cmd_elem = shell.find("command")
                if cmd_elem is not None and cmd_elem.text:
                    step = StepNode(
                        name=f"shell: {cmd_elem.text[:50]}",
                        platform=Platform.JENKINS,
                        command=cmd_elem.text,
                        shell="sh",
                    )
                    result.nodes.append(step)
                    result.edges.append(Edge(
                        edge_type=EdgeType.CALLS,
                        source_node_id=job.id,
                        target_node_id=step.id,
                    ))

            for batch in builders.iter("hudson.tasks.BatchFile"):
                cmd_elem = batch.find("command")
                if cmd_elem is not None and cmd_elem.text:
                    step = StepNode(
                        name=f"batch: {cmd_elem.text[:50]}",
                        platform=Platform.JENKINS,
                        command=cmd_elem.text,
                        shell="bat",
                    )
                    result.nodes.append(step)
                    result.edges.append(Edge(
                        edge_type=EdgeType.CALLS,
                        source_node_id=job.id,
                        target_node_id=step.id,
                    ))

            for maven in builders.iter("hudson.tasks.Maven"):
                targets = maven.find("targets")
                if targets is not None and targets.text:
                    step = StepNode(
                        name=f"maven: {targets.text[:50]}",
                        platform=Platform.JENKINS,
                        command=targets.text,
                        plugin="maven",
                    )
                    result.nodes.append(step)
                    result.edges.append(Edge(
                        edge_type=EdgeType.CALLS,
                        source_node_id=job.id,
                        target_node_id=step.id,
                    ))

        # Extract downstream project triggers
        for trigger in root.iter("hudson.tasks.BuildTrigger"):
            child_elem = trigger.find("childProjects")
            if child_elem is not None and child_elem.text:
                for child_name in child_elem.text.split(","):
                    child_name = child_name.strip()
                    if child_name:
                        child_job = JobNode(
                            name=child_name,
                            platform=Platform.JENKINS,
                        )
                        result.nodes.append(child_job)
                        result.edges.append(Edge(
                            edge_type=EdgeType.TRIGGERS,
                            source_node_id=job.id,
                            target_node_id=child_job.id,
                        ))

        # Extract parameterized triggers
        for trigger in root.iter("hudson.plugins.parameterizedtrigger.BuildTrigger"):
            for config in trigger.iter("hudson.plugins.parameterizedtrigger.BuildTriggerConfig"):
                proj = config.find("projects")
                if proj is not None and proj.text:
                    for child_name in proj.text.split(","):
                        child_name = child_name.strip()
                        if child_name:
                            child_job = JobNode(
                                name=child_name,
                                platform=Platform.JENKINS,
                            )
                            result.nodes.append(child_job)
                            result.edges.append(Edge(
                                edge_type=EdgeType.TRIGGERS,
                                source_node_id=job.id,
                                target_node_id=child_job.id,
                            ))

        logger.info(
            "Parsed freestyle job %s: %d nodes, %d edges",
            source_name, len(result.nodes), len(result.edges),
        )
        return result
