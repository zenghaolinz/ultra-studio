# Conversation Artifact Ledger Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make uploaded and generated media references deterministic across later agent turns.

**Architecture:** Add a conversation-scoped SQLite artifact projection and a resolver service. Upload requests and successful generation task transitions update the projection; the single-loop runtime injects resolved artifact context before calling the model.

**Tech Stack:** Python 3.10+, SQLite/aiosqlite, FastAPI, unittest.

---

### Task 1: Persist typed conversation artifacts

**Files:**
- Modify: `sidecar/db/sqlite.py`
- Create: `sidecar/services/conversation_artifacts.py`
- Create: `sidecar/tests/test_conversation_artifacts.py`

1. Write failing tests for migration, idempotent upsert, source ordering, and conversation cascade.
2. Run `python -m unittest sidecar.tests.test_conversation_artifacts -v`; expect failure.
3. Add the table/index and minimal async/sync repository functions.
4. Re-run the focused tests; expect PASS.
5. Commit.

### Task 2: Record uploads and completed generation outputs

**Files:**
- Modify: `sidecar/routes/agent_runs.py`
- Modify: `sidecar/services/generation_tasks.py`
- Create: `sidecar/tests/test_artifact_projection.py`

1. Write failing tests proving uploaded images are registered after the user message and successful task outputs are projected with task provenance.
2. Verify RED.
3. Implement upload and async/sync generation projection hooks with idempotent writes.
4. Verify focused tests and generation task regression tests.
5. Commit.

### Task 3: Resolve natural-language references

**Files:**
- Create: `sidecar/services/artifact_references.py`
- Create: `sidecar/tests/test_artifact_references.py`

1. Write failing tests for latest image, uploaded/generated source filters, ordinals, mixed-source requests, and missing files.
2. Verify RED.
3. Implement deterministic resolution and compact context rendering.
4. Verify GREEN.
5. Commit.

### Task 4: Inject resolved artifacts into the single-loop runtime

**Files:**
- Modify: `sidecar/routes/agent_runs.py`
- Modify: `sidecar/tests/test_agent_run_routes.py`
- Modify: `agent.md`

1. Write a failing route test showing “上传图和之前生成图” adds both canonical paths before provider execution.
2. Verify RED.
3. Register current uploads, resolve historical references, and append a system context block without changing `chat.py`.
4. Run `npm run check`, Rust tests/check, and production build.
5. Run a real-provider replay with two distinct image sources.
6. Commit.
