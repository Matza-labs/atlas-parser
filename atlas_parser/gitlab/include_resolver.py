"""GitLab CI include/extends resolver.

Resolves `include:` and `extends:` directives in .gitlab-ci.yml files.
Since the parser runs on already-fetched content, include resolution
merges pre-fetched content rather than making API calls.
"""

from __future__ import annotations

import copy
import logging
from typing import Any

import yaml

logger = logging.getLogger(__name__)


def resolve_extends(data: dict[str, Any]) -> dict[str, Any]:
    """Resolve `extends:` references within a GitLab CI config.

    When a job uses `extends: .template`, the template's keys are
    merged (deep) into the job, with the job's own keys taking precedence.

    Args:
        data: Parsed .gitlab-ci.yml dict.

    Returns:
        New dict with all `extends:` resolved.
    """
    resolved = copy.deepcopy(data)
    templates = {k: v for k, v in resolved.items() if k.startswith(".") and isinstance(v, dict)}

    for key, job_def in resolved.items():
        if not isinstance(job_def, dict) or key.startswith("."):
            continue

        extends = job_def.get("extends")
        if not extends:
            continue

        if isinstance(extends, str):
            extends = [extends]

        # Apply templates in order (first = lowest priority)
        merged = {}
        for template_name in extends:
            template = templates.get(template_name, {})
            if template:
                merged = _deep_merge(merged, copy.deepcopy(template))
            else:
                logger.warning("Template %s not found for job %s", template_name, key)

        # Job's own keys override template
        merged = _deep_merge(merged, job_def)
        merged.pop("extends", None)
        resolved[key] = merged

    return resolved


def resolve_yaml_anchors(content: str) -> dict[str, Any]:
    """Parse YAML with anchor/alias resolution (built into PyYAML).

    Args:
        content: Raw YAML string.

    Returns:
        Parsed dict with anchors resolved.
    """
    return yaml.safe_load(content) or {}


def merge_includes(
    base: dict[str, Any],
    included_configs: list[dict[str, Any]],
) -> dict[str, Any]:
    """Merge included config files into the base config.

    Include order: earlier includes have lower priority.
    Base config (the main .gitlab-ci.yml) has highest priority.

    Args:
        base: The main .gitlab-ci.yml parsed dict.
        included_configs: List of parsed include file dicts, in order.

    Returns:
        Merged config dict.
    """
    merged: dict[str, Any] = {}
    for inc in included_configs:
        merged = _deep_merge(merged, inc)

    # Base overrides everything
    merged = _deep_merge(merged, base)
    return merged


def _deep_merge(base: dict, override: dict) -> dict:
    """Deep merge two dicts. Override wins on conflicts.

    Lists are replaced, not appended.
    """
    result = copy.deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result
