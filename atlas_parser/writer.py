"""CI config writers — generate modified CI configuration files.

Each writer takes a RefactorPlan and the original config, applies
the suggestions, and outputs the modified configuration.
"""

from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod

from atlas_sdk.models.refactors import RefactorPlan

logger = logging.getLogger(__name__)


class ConfigWriter(ABC):
    """Abstract config writer — one per CI platform."""

    platform: str = ""

    @abstractmethod
    def apply(self, original_config: str, plan: RefactorPlan) -> str:
        """Apply a refactor plan to an original config and return the modified config.

        Args:
            original_config: The original CI config as a string.
            plan: The refactor plan containing suggestions.

        Returns:
            The modified config string.
        """

    def _apply_snippet_replacement(self, config: str, before: str, after: str) -> str:
        """Replace a before snippet with its after snippet in the config.

        Uses normalized whitespace matching for flexibility.
        """
        # Try exact match first
        if before in config:
            return config.replace(before, after, 1)

        # Try with normalized whitespace
        before_norm = re.sub(r'\s+', r'\\s+', re.escape(before.strip()))
        match = re.search(before_norm, config)
        if match:
            return config[:match.start()] + after + config[match.end():]

        # If no match, append the fix as a comment
        logger.warning("Could not find exact match for before snippet, appending fix")
        return config + f"\n# AUTO-FIX applied:\n{after}\n"


class JenkinsfileWriter(ConfigWriter):
    """Writes modified Jenkinsfile configurations."""

    platform = "jenkins"

    def apply(self, original_config: str, plan: RefactorPlan) -> str:
        config = original_config
        for suggestion in plan.suggestions:
            config = self._apply_snippet_replacement(
                config, suggestion.before_snippet, suggestion.after_snippet
            )
        logger.info("JenkinsfileWriter: applied %d fix(es)", len(plan.suggestions))
        return config


class GitLabYAMLWriter(ConfigWriter):
    """Writes modified .gitlab-ci.yml configurations."""

    platform = "gitlab"

    def apply(self, original_config: str, plan: RefactorPlan) -> str:
        config = original_config
        for suggestion in plan.suggestions:
            config = self._apply_snippet_replacement(
                config, suggestion.before_snippet, suggestion.after_snippet
            )
        logger.info("GitLabYAMLWriter: applied %d fix(es)", len(plan.suggestions))
        return config


class GitHubActionsWriter(ConfigWriter):
    """Writes modified GitHub Actions workflow YAML."""

    platform = "github_actions"

    def apply(self, original_config: str, plan: RefactorPlan) -> str:
        config = original_config
        for suggestion in plan.suggestions:
            config = self._apply_snippet_replacement(
                config, suggestion.before_snippet, suggestion.after_snippet
            )
        logger.info("GitHubActionsWriter: applied %d fix(es)", len(plan.suggestions))
        return config


# Writer registry
WRITER_REGISTRY: dict[str, type[ConfigWriter]] = {
    "jenkins": JenkinsfileWriter,
    "gitlab": GitLabYAMLWriter,
    "github_actions": GitHubActionsWriter,
}


def get_writer(platform: str) -> ConfigWriter:
    """Get the appropriate writer for a platform.

    Args:
        platform: Platform identifier (jenkins, gitlab, github_actions).

    Returns:
        ConfigWriter instance.

    Raises:
        ValueError: If platform is not supported.
    """
    cls = WRITER_REGISTRY.get(platform)
    if not cls:
        raise ValueError(f"No writer for platform: {platform}")
    return cls()
