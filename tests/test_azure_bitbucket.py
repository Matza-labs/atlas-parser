"""Tests for Azure and Bitbucket parsers."""

from atlas_parser.azure.yaml_parser import AzureYAMLParser
from atlas_parser.bitbucket.yaml_parser import BitbucketYAMLParser


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
