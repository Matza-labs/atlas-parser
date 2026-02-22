"""Unit tests for atlas-parser — all parsers and the orchestrator."""

import pytest

from atlas_sdk.enums import EdgeType, NodeType, Platform
from atlas_parser import (
    DeclarativeParser,
    FreestyleParser,
    GitLabYAMLParser,
    ParserOrchestrator,
    ScriptedParser,
    resolve_extends,
)


# ── Test fixtures ─────────────────────────────────────────────────────

DECLARATIVE_JENKINSFILE = """\
pipeline {
    agent any
    environment {
        DB_HOST = 'localhost'
        SECRET_TOKEN = credentials('my-secret')
    }
    options {
        timeout(time: 30, unit: 'MINUTES')
    }
    stages {
        stage('Build') {
            steps {
                sh 'make build'
            }
        }
        stage('Test') {
            steps {
                sh 'make test'
            }
        }
        stage('Deploy') {
            steps {
                sh 'make deploy'
                build job: 'downstream-notifier'
            }
        }
    }
}
"""

SCRIPTED_JENKINSFILE = """\
node('linux') {
    stage('Checkout') {
        checkout scm
    }
    stage('Build') {
        sh 'mvn clean package'
    }
    stage('Test') {
        withCredentials([usernamePassword(credentialsId: 'deploy-creds', ...)]) {
            sh 'mvn verify'
        }
    }
    stage('Deploy') {
        build job: 'deploy-to-staging'
    }
}
"""

FREESTYLE_XML = """\
<project>
    <scm class="hudson.plugins.git.GitSCM">
        <userRemoteConfigs>
            <hudson.plugins.git.UserRemoteConfig>
                <url>https://github.com/org/my-app.git</url>
            </hudson.plugins.git.UserRemoteConfig>
        </userRemoteConfigs>
        <branches>
            <hudson.plugins.git.BranchSpec>
                <name>*/main</name>
            </hudson.plugins.git.BranchSpec>
        </branches>
    </scm>
    <builders>
        <hudson.tasks.Shell>
            <command>make build</command>
        </hudson.tasks.Shell>
        <hudson.tasks.Maven>
            <targets>clean install</targets>
        </hudson.tasks.Maven>
    </builders>
    <publishers>
        <hudson.tasks.BuildTrigger>
            <childProjects>integration-tests, deploy-prod</childProjects>
        </hudson.tasks.BuildTrigger>
    </publishers>
</project>
"""

GITLAB_CI_YAML = """\
image: python:3.11

stages:
  - build
  - test
  - deploy

variables:
  DB_HOST: "localhost"
  SECRET_TOKEN: "should-be-masked"

build-job:
  stage: build
  script:
    - pip install -r requirements.txt
    - python setup.py build
  artifacts:
    paths:
      - dist/

test-job:
  stage: test
  image: python:3.11-slim
  services:
    - postgres:15
  script:
    - pytest tests/
  needs:
    - build-job

deploy-job:
  stage: deploy
  script:
    - ./deploy.sh
  environment:
    name: production
    url: https://prod.example.com
"""

GITLAB_WITH_EXTENDS = """\
.default_job:
  image: python:3.11
  before_script:
    - pip install -r requirements.txt

stages:
  - test

unit_test:
  extends: .default_job
  stage: test
  script:
    - pytest tests/
"""


# ── Declarative parser tests ─────────────────────────────────────────


class TestDeclarativeParser:
    def test_basic_pipeline(self):
        parser = DeclarativeParser()
        result = parser.parse(DECLARATIVE_JENKINSFILE, "my-pipeline")

        assert len(result.errors) == 0
        # Pipeline + 3 stages + 3 sh steps + 1 downstream + 1 secret + 1 env
        node_types = [n.node_type for n in result.nodes]
        assert NodeType.PIPELINE in node_types
        assert node_types.count(NodeType.STAGE) == 3
        assert NodeType.SECRET_REF in node_types

    def test_stages_extracted(self):
        parser = DeclarativeParser()
        result = parser.parse(DECLARATIVE_JENKINSFILE, "test")
        stages = [n for n in result.nodes if n.node_type == NodeType.STAGE]
        names = [s.name for s in stages]
        assert "Build" in names
        assert "Test" in names
        assert "Deploy" in names

    def test_downstream_trigger(self):
        parser = DeclarativeParser()
        result = parser.parse(DECLARATIVE_JENKINSFILE, "test")
        jobs = [n for n in result.nodes if n.node_type == NodeType.JOB]
        assert any(j.name == "downstream-notifier" for j in jobs)
        trigger_edges = [e for e in result.edges if e.edge_type == EdgeType.TRIGGERS]
        assert len(trigger_edges) >= 1

    def test_credential_extraction(self):
        parser = DeclarativeParser()
        result = parser.parse(DECLARATIVE_JENKINSFILE, "test")
        secrets = [n for n in result.nodes if n.node_type == NodeType.SECRET_REF]
        assert any(s.key == "my-secret" for s in secrets)

    def test_no_pipeline_block(self):
        parser = DeclarativeParser()
        result = parser.parse("// just a comment", "empty")
        assert len(result.errors) == 1

    def test_agent_extraction(self):
        parser = DeclarativeParser()
        result = parser.parse(DECLARATIVE_JENKINSFILE, "test")
        pipeline = result.nodes[0]
        assert pipeline.agent == "any"


# ── Scripted parser tests ────────────────────────────────────────────


class TestScriptedParser:
    def test_basic_scripted(self):
        parser = ScriptedParser()
        result = parser.parse(SCRIPTED_JENKINSFILE, "my-scripted")

        assert len(result.errors) == 0
        node_types = [n.node_type for n in result.nodes]
        assert NodeType.PIPELINE in node_types
        assert node_types.count(NodeType.STAGE) == 4

    def test_node_label(self):
        parser = ScriptedParser()
        result = parser.parse(SCRIPTED_JENKINSFILE, "test")
        pipeline = result.nodes[0]
        assert pipeline.agent == "linux"

    def test_downstream_trigger(self):
        parser = ScriptedParser()
        result = parser.parse(SCRIPTED_JENKINSFILE, "test")
        jobs = [n for n in result.nodes if n.node_type == NodeType.JOB]
        assert any(j.name == "deploy-to-staging" for j in jobs)

    def test_credentials(self):
        parser = ScriptedParser()
        result = parser.parse(SCRIPTED_JENKINSFILE, "test")
        secrets = [n for n in result.nodes if n.node_type == NodeType.SECRET_REF]
        assert any(s.key == "deploy-creds" for s in secrets)


# ── Freestyle parser tests ───────────────────────────────────────────


class TestFreestyleParser:
    def test_basic_freestyle(self):
        parser = FreestyleParser()
        result = parser.parse(FREESTYLE_XML, "my-freestyle")

        assert len(result.errors) == 0
        node_types = [n.node_type for n in result.nodes]
        assert NodeType.PIPELINE in node_types
        assert NodeType.REPOSITORY in node_types
        assert NodeType.STEP in node_types

    def test_git_scm(self):
        parser = FreestyleParser()
        result = parser.parse(FREESTYLE_XML, "test")
        repos = [n for n in result.nodes if n.node_type == NodeType.REPOSITORY]
        assert len(repos) == 1
        assert "my-app" in repos[0].name

    def test_shell_builders(self):
        parser = FreestyleParser()
        result = parser.parse(FREESTYLE_XML, "test")
        steps = [n for n in result.nodes if n.node_type == NodeType.STEP]
        commands = [s.command for s in steps]
        assert "make build" in commands
        assert "clean install" in commands

    def test_downstream_triggers(self):
        parser = FreestyleParser()
        result = parser.parse(FREESTYLE_XML, "test")
        jobs = [n for n in result.nodes if n.node_type == NodeType.JOB]
        names = [j.name for j in jobs]
        assert "integration-tests" in names
        assert "deploy-prod" in names

    def test_invalid_xml(self):
        parser = FreestyleParser()
        result = parser.parse("<not>valid xml<", "bad")
        assert len(result.errors) == 1


# ── GitLab YAML parser tests ─────────────────────────────────────────


class TestGitLabYAMLParser:
    def test_basic_gitlab(self):
        parser = GitLabYAMLParser()
        result = parser.parse(GITLAB_CI_YAML, "my-project")

        assert len(result.errors) == 0
        node_types = [n.node_type for n in result.nodes]
        assert NodeType.PIPELINE in node_types
        assert node_types.count(NodeType.STAGE) == 3

    def test_stages_extracted(self):
        parser = GitLabYAMLParser()
        result = parser.parse(GITLAB_CI_YAML, "test")
        stages = [n for n in result.nodes if n.node_type == NodeType.STAGE]
        names = [s.name for s in stages]
        assert "build" in names
        assert "test" in names
        assert "deploy" in names

    def test_jobs_extracted(self):
        parser = GitLabYAMLParser()
        result = parser.parse(GITLAB_CI_YAML, "test")
        steps = [n for n in result.nodes if n.node_type == NodeType.STEP]
        names = [s.name for s in steps]
        assert "build-job" in names
        assert "test-job" in names
        assert "deploy-job" in names

    def test_artifacts(self):
        parser = GitLabYAMLParser()
        result = parser.parse(GITLAB_CI_YAML, "test")
        artifacts = [n for n in result.nodes if n.node_type == NodeType.ARTIFACT]
        assert len(artifacts) == 1
        assert "dist/" in artifacts[0].path

    def test_services(self):
        parser = GitLabYAMLParser()
        result = parser.parse(GITLAB_CI_YAML, "test")
        services = [n for n in result.nodes if n.node_type == NodeType.EXTERNAL_SERVICE]
        assert any("postgres" in s.name for s in services)

    def test_environment(self):
        parser = GitLabYAMLParser()
        result = parser.parse(GITLAB_CI_YAML, "test")
        envs = [n for n in result.nodes if n.node_type == NodeType.ENVIRONMENT]
        assert any(e.name == "production" for e in envs)

    def test_secret_variable_detection(self):
        parser = GitLabYAMLParser()
        result = parser.parse(GITLAB_CI_YAML, "test")
        secrets = [n for n in result.nodes if n.node_type == NodeType.SECRET_REF]
        assert any(s.key == "SECRET_TOKEN" for s in secrets)

    def test_invalid_yaml(self):
        parser = GitLabYAMLParser()
        result = parser.parse(": invalid: yaml: {{", "bad")
        assert len(result.errors) >= 1


# ── Include resolver tests ───────────────────────────────────────────


class TestIncludeResolver:
    def test_resolve_extends(self):
        import yaml
        data = yaml.safe_load(GITLAB_WITH_EXTENDS)
        resolved = resolve_extends(data)

        assert "unit_test" in resolved
        job = resolved["unit_test"]
        assert job.get("image") == "python:3.11"
        assert "extends" not in job
        assert "script" in job

    def test_extends_override(self):
        data = {
            ".base": {"image": "python:3.9", "script": ["echo base"]},
            "test": {"extends": ".base", "image": "python:3.11"},
        }
        resolved = resolve_extends(data)
        assert resolved["test"]["image"] == "python:3.11"


# ── Orchestrator tests ───────────────────────────────────────────────


class TestOrchestrator:
    def test_route_declarative(self):
        orch = ParserOrchestrator()
        result = orch.parse_all([{
            "job_name": "my-pipeline",
            "path": "Jenkinsfile",
            "content": DECLARATIVE_JENKINSFILE,
            "job_type": "pipeline",
            "platform": "jenkins",
        }])
        assert len(result.nodes) > 0
        assert any(n.node_type == NodeType.PIPELINE for n in result.nodes)

    def test_route_freestyle(self):
        orch = ParserOrchestrator()
        result = orch.parse_all([{
            "job_name": "my-freestyle",
            "path": "config.xml",
            "content": FREESTYLE_XML,
            "job_type": "freestyle",
            "platform": "jenkins",
        }])
        assert any(n.node_type == NodeType.REPOSITORY for n in result.nodes)

    def test_route_gitlab(self):
        orch = ParserOrchestrator()
        result = orch.parse_all([{
            "job_name": "my-project",
            "path": ".gitlab-ci.yml",
            "content": GITLAB_CI_YAML,
            "job_type": "gitlab_ci",
            "platform": "gitlab",
        }])
        assert any(n.node_type == NodeType.STAGE for n in result.nodes)

    def test_multiple_configs(self):
        orch = ParserOrchestrator()
        result = orch.parse_all([
            {"job_name": "j1", "content": DECLARATIVE_JENKINSFILE, "job_type": "pipeline", "platform": "jenkins"},
            {"job_name": "g1", "content": GITLAB_CI_YAML, "job_type": "gitlab_ci", "platform": "gitlab"},
        ])
        # Both should produce nodes
        pipelines = [n for n in result.nodes if n.node_type == NodeType.PIPELINE]
        assert len(pipelines) == 2

    def test_empty_content_error(self):
        orch = ParserOrchestrator()
        result = orch.parse_all([{
            "job_name": "empty", "content": "", "job_type": "pipeline", "platform": "jenkins",
        }])
        assert len(result.errors) == 1
