"""Unit tests for GitHub Actions YAML parser."""

from atlas_sdk.enums import EdgeType, Platform
from atlas_sdk.models.nodes import (
    EnvironmentNode,
    JobNode,
    PipelineNode,
    SecretRefNode,
    StepNode,
)

from atlas_parser.github.yaml_parser import GitHubYAMLParser

RAW_YAML = """
name: CI Workflow
on: [push]

env:
  GLOBAL_VAR: "true"

jobs:
  build:
    name: Build Project
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v3
      - name: Compile
        run: |
          make build
        env:
          SECRET_TOKEN: ${{ secrets.MY_TOKEN }}

  deploy:
    name: Deploy App
    runs-on: ubuntu-latest
    needs: build
    environment: production
    steps:
      - name: Deploy
        run: make deploy
        env:
          API_KEY: ${{ secrets.PROD_API_KEY }}
"""


def test_github_yaml_parser():
    parser = GitHubYAMLParser()
    result = parser.parse(RAW_YAML, source_name="owner/repo: .github/workflows/ci.yml")

    assert not result.errors

    pipelines = [n for n in result.nodes if isinstance(n, PipelineNode)]
    jobs = [n for n in result.nodes if isinstance(n, JobNode)]
    steps = [n for n in result.nodes if isinstance(n, StepNode)]
    envs = [n for n in result.nodes if isinstance(n, EnvironmentNode)]
    secrets = [n for n in result.nodes if isinstance(n, SecretRefNode)]

    # Check Pipeline
    assert len(pipelines) == 1
    assert pipelines[0].name == "CI Workflow"
    assert pipelines[0].platform == Platform.GITHUB_ACTIONS

    # Check Jobs
    assert len(jobs) == 2
    b_job = next(j for j in jobs if j.name == "CI Workflow::Build Project")
    d_job = next(j for j in jobs if j.name == "CI Workflow::Deploy App")
    assert b_job.parameters.get("agent_label") == "ubuntu-latest"
    assert d_job.parameters.get("agent_label") == "ubuntu-latest"

    # Check Steps
    assert len(steps) == 3
    s1 = next(s for s in steps if s.name == "CI Workflow::Build Project / Checkout")
    s2 = next(s for s in steps if s.name == "CI Workflow::Build Project / Compile")
    s3 = next(s for s in steps if s.name == "CI Workflow::Deploy App / Deploy")
    assert s1.shell == "action"
    assert "actions/checkout@v3" in s1.command
    assert s2.shell == "default"
    assert "make build" in s2.command
    assert s3.shell == "default"

    # Check Environment
    assert len(envs) == 1
    assert envs[0].name == "production"

    # Check Secrets
    assert len(secrets) == 2
    assert any(s.key == "MY_TOKEN" for s in secrets)
    assert any(s.key == "PROD_API_KEY" for s in secrets)

    # Check Edges
    # Pipeline calls 2 jobs
    assert sum(1 for e in result.edges if e.source_node_id == pipelines[0].id and e.edge_type == EdgeType.CALLS) == 2
    # Build job calls 2 steps
    assert sum(1 for e in result.edges if e.source_node_id == b_job.id and e.edge_type == EdgeType.CALLS) == 2
    # Deploy job calls 1 step
    assert sum(1 for e in result.edges if e.source_node_id == d_job.id and e.edge_type == EdgeType.CALLS) == 1
    # Deploy depends on Build
    assert sum(1 for e in result.edges if e.source_node_id == d_job.id and e.target_node_id == b_job.id and e.edge_type == EdgeType.DEPENDS_ON) == 1
    # Deploy deploys to production
    assert sum(1 for e in result.edges if e.source_node_id == d_job.id and e.target_node_id == envs[0].id and e.edge_type == EdgeType.DEPLOYS_TO) == 1
    # Compile step consumes MY_TOKEN
    assert sum(1 for e in result.edges if e.source_node_id == s2.id and e.edge_type == EdgeType.CONSUMES) == 1
    # Deploy step consumes PROD_API_KEY
    assert sum(1 for e in result.edges if e.source_node_id == s3.id and e.edge_type == EdgeType.CONSUMES) == 1


def test_github_yaml_parser_invalid():
    parser = GitHubYAMLParser()
    result = parser.parse("not: valid: yaml: [", source_name="bad.yml")
    assert len(result.errors) == 1
    assert "Invalid YAML" in result.errors[0]
