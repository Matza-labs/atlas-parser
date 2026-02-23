"""Tests for ConfigWriter — round-trip verification."""

from atlas_sdk.models.refactors import RefactorPlan, RefactorSuggestion
from atlas_parser.writer import (
    JenkinsfileWriter,
    GitLabYAMLWriter,
    GitHubActionsWriter,
    get_writer,
    WRITER_REGISTRY,
)


def test_all_three_writers_registered():
    assert "jenkins" in WRITER_REGISTRY
    assert "gitlab" in WRITER_REGISTRY
    assert "github_actions" in WRITER_REGISTRY


def test_get_writer():
    writer = get_writer("github_actions")
    assert isinstance(writer, GitHubActionsWriter)


def test_get_writer_invalid():
    import pytest
    with pytest.raises(ValueError):
        get_writer("azure_pipelines")


def test_github_writer_applies_fix():
    original = """name: CI
on: push
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - run: npm install
      - run: npm test"""

    plan = RefactorPlan(
        name="CI",
        suggestions=[
            RefactorSuggestion(
                rule_id="no-timeout",
                description="Add timeout",
                before_snippet="runs-on: ubuntu-latest",
                after_snippet="runs-on: ubuntu-latest\n    timeout-minutes: 30",
            ),
        ],
    )

    writer = GitHubActionsWriter()
    result = writer.apply(original, plan)

    assert "timeout-minutes: 30" in result
    assert "runs-on: ubuntu-latest" in result


def test_jenkins_writer_applies_fix():
    original = """pipeline {
    agent any
    stages {
        stage('Build') {
            steps {
                sh 'make build'
            }
        }
    }
}"""

    plan = RefactorPlan(
        name="Build",
        suggestions=[
            RefactorSuggestion(
                rule_id="no-timeout",
                description="Add timeout",
                before_snippet="agent any",
                after_snippet="agent any\n    options {\n        timeout(time: 30, unit: 'MINUTES')\n    }",
            ),
        ],
    )

    writer = JenkinsfileWriter()
    result = writer.apply(original, plan)

    assert "timeout(time: 30" in result


def test_gitlab_writer_applies_fix():
    original = """stages:
  - build
  - test

build:
  stage: build
  script:
    - make build"""

    plan = RefactorPlan(
        name="CI",
        suggestions=[
            RefactorSuggestion(
                rule_id="no-cache",
                description="Add cache",
                before_snippet="script:\n    - make build",
                after_snippet="cache:\n    paths:\n      - .cache/\n  script:\n    - make build",
            ),
        ],
    )

    writer = GitLabYAMLWriter()
    result = writer.apply(original, plan)

    assert "cache:" in result
    assert ".cache/" in result


def test_no_match_appends_comment():
    original = "some random config"
    plan = RefactorPlan(
        name="test",
        suggestions=[
            RefactorSuggestion(
                rule_id="test",
                description="test fix",
                before_snippet="nonexistent-snippet",
                after_snippet="fixed-snippet",
            ),
        ],
    )

    writer = GitHubActionsWriter()
    result = writer.apply(original, plan)

    # Should append when no match found
    assert "AUTO-FIX" in result or "fixed-snippet" in result
