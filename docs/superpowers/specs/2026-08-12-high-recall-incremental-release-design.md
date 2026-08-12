# High-Recall Incremental Release Design

**Date:** 2026-08-12

**Target:** `172.16.102.250`

**Release image:** `ragflow:v0.23.1.23-custom`

## Goal

Publish the complete high-recall retrieval path while preserving the knowledge-graph implementation and historical fixes already present in `ragflow:v0.23.1.22-custom`. Restore the GPUStack transcription URL fix and the `user_prompt` field name at the same time.

## Release Baseline

The new image must be derived from `ragflow:v0.23.1.22-custom` with image ID `sha256:5ed004b3911a99a30c38dab7066979458b3bc940569cd4a466da8b4528aae448`.

The build must use a new isolated release context copied from the retained `.22` deployment context. It must not copy either local Git worktree wholesale because both worktrees contain unrelated or uncommitted changes.

## Included Changes

The backend release overlay includes the complete high-recall call chain:

- `rag/nlp/high_recall.py`
- `rag/nlp/search.py`
- `rag/utils/es_conn.py`
- `common/settings.py`
- `agent/tools/retrieval.py`
- `api/apps/chunk_app.py`
- `api/apps/sdk/dify_retrieval.py`
- `api/apps/sdk/doc.py`
- `api/apps/sdk/session.py`
- `conf/service_conf.yaml`
- `docker/service_conf.yaml.template`

The frontend overlay includes the high-recall controls and request propagation files already identified by the deployment audit. The frontend source baseline is the current knowledge-graph worktree, and only the approved high-recall frontend changes are applied before producing `web/dist`.

The release also restores:

- GPUStack transcription base URL normalization and safe audio file handling in `rag/llm/sequence2txt_model.py`.
- `user_prompt` in place of the invalid `user_prompt.txt` key in `agent/component/agent_with_tools.py`, `api/apps/memories_app.py`, `api/utils/memory_utils.py`, and `graphrag/light/graph_prompt.py`.

## Configuration

`rerank_top_n` defaults to `64` consistently in:

- `rag/nlp/high_recall.py`
- `conf/service_conf.yaml`
- `docker/service_conf.yaml.template`
- frontend form defaults
- affected regression tests

The maximum remains `512`. Existing requests that explicitly provide `rerank_top_n` continue to override the default within validation bounds.

## Preservation Rules

The release must preserve all `.22` knowledge-graph files and historical fixes. The build process will compare the `.23` candidate against `.22` and reject any changed file outside the approved overlay, generated frontend assets, and image metadata.

MySQL, Elasticsearch, Redis, MinIO, Neo4j, and GDS are not rebuilt or restarted. Only the RAGFlow application container is replaced.

## Verification

Before image construction:

- Run high-recall helper and orchestration tests.
- Run GPUStack transcription regression tests.
- Run focused `user_prompt` contract tests or source assertions where no isolated contract test exists.
- Run the retained knowledge-graph backend and frontend suites.
- Run historical PDF, MinerU, cancellation, strict-delete, Office compatibility, folder-move, and reranker regressions.
- Run scoped Python lint, frontend lint/type checks, and the production frontend build.

After image construction, an ephemeral container must verify:

- all overlay file hashes;
- high-recall imports and configuration;
- normalized default value `64`;
- absence of `user_prompt.txt` in the four corrected files;
- GPUStack regression tests;
- retained knowledge-graph source hashes.

After deployment, verify container health and restart count, API availability, knowledge-graph API and Neo4j/GDS health, high-recall runtime markers, frontend asset availability, and representative retrieval behavior.

## Deployment And Rollback

Before deployment, save the current Docker `.env`, `service_conf.yaml.template`, image ID, and Compose configuration in a timestamped backup directory. Keep `.22` tagged locally.

Set `RAGFLOW_IMAGE=ragflow:v0.23.1.23-custom` and recreate only the `ragflow-cpu` service. A service interruption of approximately one to three minutes is accepted.

If any post-deployment check fails, restore the backed-up `.env` and configuration, set the image back to `ragflow:v0.23.1.22-custom`, recreate only `ragflow-cpu`, and repeat the application and graph health checks.

## Acceptance Criteria

- The running container uses `ragflow:v0.23.1.23-custom` and has zero unexpected restarts.
- High-recall retrieval is present end to end with a default `rerank_top_n` of `64`.
- GPUStack transcription URL regression tests pass.
- The four affected modules use `user_prompt`, with no remaining `user_prompt.txt` occurrences.
- Knowledge-graph behavior and the retained historical fixes pass their focused regressions.
- Rollback artifacts are present and `.22` remains immediately deployable.
