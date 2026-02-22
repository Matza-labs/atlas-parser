# atlas-parser

Static Analysis Engine for **PipelineAtlas** — deterministic pipeline parsing.

## Purpose

Parses CI/CD pipeline definitions into structured graph nodes and edges. Fully deterministic — **no LLM is used for structure extraction**.

## Supported Formats

| Format | Module | Status |
|--------|--------|--------|
| Jenkins Declarative Pipeline | `atlas_parser.jenkins.declarative` | ✅ Completed |
| Jenkins Scripted Pipeline | `atlas_parser.jenkins.scripted` | ✅ Completed |
| Jenkins Freestyle XML | `atlas_parser.jenkins.freestyle` | ✅ Completed |
| GitLab CI YAML | `atlas_parser.gitlab.yaml_parser` | ✅ Completed |
| GitLab Includes/Extends | `atlas_parser.gitlab.include_resolver` | ✅ Completed |
| GitHub Actions YAML | — | 🟡 Phase 2 |

## Input

Raw pipeline configuration content (received from `atlas-scanner` via Redis Streams).

## Output

Structured `Node` and `Edge` objects (from `atlas-sdk`) published to `atlas-graph`.

## Dependencies

- `atlas-sdk` (shared models)
- `pyyaml` (YAML parsing)
- `redis` (Redis Streams)

## Related Services

Receives from ← `atlas-scanner` (via Redis Streams)
Publishes to → `atlas-graph`
