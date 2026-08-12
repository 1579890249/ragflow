# High-Recall Incremental Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and publish `ragflow:v0.23.1.23-custom` from the deployed `.22` graph baseline with the complete high-recall path, GPUStack transcription fix, and `user_prompt` fix.

**Architecture:** Reconstruct an isolated source tree from the `.22` graph release manifest, apply only reviewed high-recall and hotfix overlays, and produce a thin Docker layer based on `.22`. Verify the source tree, frontend bundle, candidate image, and running container at separate gates; retain `.22` and timestamped configuration backups for rollback.

**Tech Stack:** Git worktrees, Python 3.12, pytest, ruff, React/TypeScript, npm, Docker, Docker Compose, SSH, Neo4j/GDS.

---

### Task 1: Create The Isolated Release Source

**Files:**
- Create worktree: `ragflow-worktrees/release-v0.23.1.23`
- Read: server `.deployment-context-v0.23.1.22/source-files.txt`
- Read: server `.deployment-context-v0.23.1.22/source/`

- [ ] Verify `ragflow-worktrees` is ignored and create `release/v0.23.1.23` from commit `41299b28e`.
- [ ] Copy only the `.22` manifest paths from the graph worktree into the release worktree and compare their SHA-256 hashes with the retained `.22` context.
- [ ] Run the retained graph backend and frontend contract suites to establish the release baseline.

### Task 2: Apply High-Recall With Default 64

**Files:**
- Create: `rag/nlp/high_recall.py`
- Modify: `rag/nlp/search.py`
- Modify: `rag/utils/es_conn.py`
- Modify: `common/settings.py`
- Modify: `agent/tools/retrieval.py`
- Modify: `api/apps/chunk_app.py`
- Modify: `api/apps/sdk/dify_retrieval.py`
- Modify: `api/apps/sdk/doc.py`
- Modify: `api/apps/sdk/session.py`
- Modify: `conf/service_conf.yaml`
- Modify: `docker/service_conf.yaml.template`
- Modify the approved high-recall frontend request, form, interface, and locale files.
- Test: `test/unit_test/rag/test_high_recall.py`
- Test: `test/unit_test/rag/test_high_recall_search.py`

- [ ] Apply the working high-recall patch onto the graph baseline and resolve shared files by retaining both graph and retrieval behavior.
- [ ] Change `DEFAULT_RERANK_TOP_N`, backend YAML defaults, frontend defaults, and default-value test assertions from `128` to `64`.
- [ ] Run high-recall tests and require zero failures.
- [ ] Run scoped ruff and frontend lint/type checks.

### Task 3: Restore The Two Regressed Fixes

**Files:**
- Modify: `rag/llm/sequence2txt_model.py`
- Modify: `agent/component/agent_with_tools.py`
- Modify: `api/apps/memories_app.py`
- Modify: `api/utils/memory_utils.py`
- Modify: `graphrag/light/graph_prompt.py`
- Test: `test/unit_test/rag/llm/test_sequence2txt_model.py`
- Test: memory API tests and source contract assertions.

- [ ] Apply the committed GPUStack implementation from `cc467f016` and its regression test.
- [ ] Replace the invalid `user_prompt.txt` contract with `user_prompt` in exactly the four audited modules.
- [ ] Run the GPUStack and memory/user-prompt regressions and require zero failures.

### Task 4: Run Preservation Regressions And Build Frontend

**Files:**
- Verify graph, PDF, MinerU, cancellation, strict-delete, Office, folder, DB connection, reranker, and high-recall test suites.
- Build output: `web/dist/`

- [ ] Run all focused backend suites used for `.22` plus the new retrieval and hotfix suites.
- [ ] Run graph-focused frontend tests and high-recall frontend checks.
- [ ] Run `npm run build` in the isolated `web` tree and require a successful production bundle.
- [ ] Scan the release diff and reject changes outside the approved graph baseline, high-recall overlay, two restored fixes, tests, and generated frontend bundle.

### Task 5: Build And Validate Candidate Image

**Files:**
- Create server context: `.deployment-context-v0.23.1.23/`
- Create server tests: `.deployment-tests-v0.23.1.23/`
- Create image: `ragflow:v0.23.1.23-custom`

- [ ] Upload the approved source overlay, source manifest, tests, and `web/dist` into new `.23` directories without changing `.22` artifacts.
- [ ] Create a Dockerfile with `FROM ragflow:v0.23.1.22-custom`, `COPY source/ /ragflow/`, and `COPY web-dist/ /ragflow/web/dist/`.
- [ ] Build the candidate and require Docker exit code zero.
- [ ] In an ephemeral candidate container, run focused tests and verify overlay hashes, graph preservation hashes, high-recall imports, default `64`, no `user_prompt.txt`, and GPUStack URL behavior.

### Task 6: Deploy And Verify

**Files:**
- Backup: `.deployment-backups/v0.23.1.23-before-<timestamp>/`
- Modify server: `docker/.env`
- Modify server: `docker/service_conf.yaml.template`

- [ ] Save `.env`, service configuration, Compose configuration, current container inspection, and `.22` image ID in the timestamped backup directory.
- [ ] Update the mounted service template to the verified `.23` template and set `RAGFLOW_IMAGE=ragflow:v0.23.1.23-custom`.
- [ ] Recreate only `ragflow-cpu` with Docker Compose.
- [ ] Verify image ID, health, restart count, HTTP/API availability, graph API, Neo4j/GDS, retrieval runtime markers, and frontend assets.
- [ ] If any required check fails, restore the backup and recreate `ragflow-cpu` from `.22`; otherwise leave `.22` tagged and record final hashes and status.
