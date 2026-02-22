"""PipelineAtlas Parser — deterministic CI/CD pipeline parsing."""

__version__ = "0.1.0"

from atlas_parser.base import BaseParser, ParseResult  # noqa: F401
from atlas_parser.gitlab.include_resolver import merge_includes, resolve_extends  # noqa: F401
from atlas_parser.gitlab.yaml_parser import GitLabYAMLParser  # noqa: F401
from atlas_parser.jenkins.declarative import DeclarativeParser  # noqa: F401
from atlas_parser.jenkins.freestyle import FreestyleParser  # noqa: F401
from atlas_parser.jenkins.scripted import ScriptedParser  # noqa: F401
from atlas_parser.orchestrator import ParserOrchestrator  # noqa: F401
