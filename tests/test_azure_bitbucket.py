"""Tests for Azure and Bitbucket parsers and orchestrator routing."""

from atlas_sdk.enums import Platform
from atlas_parser.azure.yaml_parser import AzureYAMLParser
from atlas_parser.bitbucket.yaml_parser import BitbucketYAMLParser
from atlas_parser.orchestrator import ParserOrchestrator


class TestAzureParser:

    def test_parses_stages_jobs_steps(self):
        config = """
trigger:
  - main

stages:
  - stage: Build
    jobs:
      - job: BuildApp
        pool:
          vmImage: ubuntu-latest
        steps:
          - script: npm install
            displayName: Install dependencies
          - script: npm test
            displayName: Run tests

  - stage: Deploy
    jobs:
      - job: DeployProd
        steps:
          - script: ./deploy.sh
            displayName: Deploy to production
"""
        parser = AzureYAMLParser()
        result = parser.parse(config, source_name="azure-ci")

        # Pipeline + 2 stages + 2 jobs + 3 steps = 8 nodes
        assert len(result.nodes) >= 8
        assert len(result.edges) >= 7
        assert result.nodes[0].name == "azure-ci"

    def test_parses_top_level_steps(self):
        config = """
trigger:
  - main

steps:
  - script: echo hello
    displayName: Say Hello
"""
        parser = AzureYAMLParser()
        result = parser.parse(config, source_name="simple")

        assert len(result.nodes) >= 2  # Pipeline + step
        assert len(result.edges) >= 1


class TestBitbucketParser:

    def test_parses_default_pipeline(self):
        config = """
pipelines:
  default:
    - step:
        name: Build
        script:
          - npm install
          - npm test
    - step:
        name: Deploy
        script:
          - ./deploy.sh
"""
        parser = BitbucketYAMLParser()
        result = parser.parse(config, source_name="bb-ci")

        # Pipeline + 2 steps = 3 nodes
        assert len(result.nodes) >= 3
        assert result.nodes[0].name == "bb-ci"

    def test_parses_branches(self):
        config = """
pipelines:
  branches:
    main:
      - step:
          name: Deploy Prod
          script:
            - ./deploy.sh
    develop:
      - step:
          name: Deploy Staging
          script:
            - ./deploy-staging.sh
"""
        parser = BitbucketYAMLParser()
        result = parser.parse(config, source_name="bb-branches")

        # Pipeline + 2 branch stages + 2 steps = 5 nodes
        assert len(result.nodes) >= 5
        branch_names = [n.name for n in result.nodes if hasattr(n, 'order')]
        assert any("main" in n.name for n in result.nodes)


class TestOrchestratorRouting:
    """Verify the orchestrator routes Azure/Bitbucket configs to the correct parsers."""

    def test_routes_azure_by_platform(self):
        config = """
trigger:
  - main
steps:
  - script: echo hello
    displayName: Build
"""
        orchestrator = ParserOrchestrator()
        result = orchestrator.parse_all([{
            "job_name": "my-azure-pipeline",
            "content": config,
            "job_type": "",
            "platform": Platform.AZURE_DEVOPS,
        }])
        assert len(result.nodes) >= 2  # at minimum: pipeline + step
        assert result.nodes[0].name == "my-azure-pipeline"

    def test_routes_azure_by_job_type(self):
        config = """
steps:
  - script: echo hello
"""
        orchestrator = ParserOrchestrator()
        result = orchestrator.parse_all([{
            "job_name": "azure-job",
            "content": config,
            "job_type": "azure_pipelines",
            "platform": "",
        }])
        assert len(result.nodes) >= 1
        assert not result.errors

    def test_routes_bitbucket_by_platform(self):
        config = """
pipelines:
  default:
    - step:
        name: Build
        script:
          - npm install
"""
        orchestrator = ParserOrchestrator()
        result = orchestrator.parse_all([{
            "job_name": "bb-repo",
            "content": config,
            "job_type": "",
            "platform": Platform.BITBUCKET,
        }])
        assert len(result.nodes) >= 2  # pipeline + step
        assert result.nodes[0].name == "bb-repo"

    def test_routes_bitbucket_by_job_type(self):
        config = """
pipelines:
  default:
    - step:
        name: Test
        script:
          - pytest
"""
        orchestrator = ParserOrchestrator()
        result = orchestrator.parse_all([{
            "job_name": "bb-test",
            "content": config,
            "job_type": "bitbucket_pipelines",
            "platform": "",
        }])
        assert len(result.nodes) >= 1
        assert not result.errors

    def test_parse_method_routes_azure(self):
        """parse() convenience method also routes Azure correctly."""
        config = "steps:\n  - script: echo hi\n"
        orchestrator = ParserOrchestrator()
        result = orchestrator.parse(config, platform=Platform.AZURE_DEVOPS)
        assert len(result.nodes) >= 1

    def test_parse_method_routes_bitbucket(self):
        """parse() convenience method also routes Bitbucket correctly."""
        config = "pipelines:\n  default:\n    - step:\n        name: Build\n        script:\n          - make\n"
        orchestrator = ParserOrchestrator()
        result = orchestrator.parse(config, platform=Platform.BITBUCKET)
        assert len(result.nodes) >= 1
