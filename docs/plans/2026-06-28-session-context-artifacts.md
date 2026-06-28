# Session Context and General Artifacts Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Remove global-memory influence from the active agent runtime and generalize conversation artifacts from images to all attached and generated files.

**Architecture:** Add a conversation-only context builder, keep global-memory storage behind inactive compatibility APIs, and extend the existing artifact ledger with generic type classification and deterministic reference resolution. Keep `chat.py` unchanged.

**Tech Stack:** Python, FastAPI, aiosqlite, unittest, TypeScript/Rust compatibility transport.

---

### Task 1: Conversation-only runtime context

**Files:**
- Create: `sidecar/services/agent_context.py`
- Create: `sidecar/tests/test_agent_context.py`
- Modify: `sidecar/routes/agent_runs.py`

1. Write failing tests proving only the requested conversation history is loaded and persona/global-memory content is absent.
2. Run the focused tests and confirm the missing context builder failure.
3. Implement the static system contract, scoped history loading, attachment path rendering, optional image encoding, and deterministic capabilities.
4. Replace `memory_mgr.build_context` in the agent route.
5. Run focused tests and commit.

### Task 2: Generic artifact registration

**Files:**
- Modify: `sidecar/services/conversation_artifacts.py`
- Modify: `sidecar/tests/test_conversation_artifacts.py`
- Modify: `sidecar/tests/test_artifact_projection.py`

1. Write failing tests for document, code, archive, audio, and unknown-file classification and registration.
2. Verify failures.
3. Implement `record_uploaded_artifacts`, generic classification, and compatibility aliasing.
4. Ensure generated output projection accepts every existing file.
5. Run focused tests and commit.

### Task 3: Generic reference resolution

**Files:**
- Modify: `sidecar/services/artifact_references.py`
- Modify: `sidecar/tests/test_artifact_references.py`

1. Write failing tests for uploaded PDFs, prior generated documents, code, ordinals, latest generic files, and mixed kinds.
2. Verify failures.
3. Generalize filtering and deterministic source/kind selection.
4. Run focused tests and commit.

### Task 4: Runtime integration

**Files:**
- Modify: `sidecar/routes/agent_runs.py`
- Modify: `sidecar/tests/test_agent_run_routes.py`
- Modify: `agent.md`

1. Write failing route tests for generic registration, generic artifact context, file capability activation, and absence of the memory manager dependency.
2. Verify failures.
3. Wire generic attachments and resolved kinds into capability selection.
4. Document the context boundary and compatibility field.
5. Run focused tests and commit.

### Task 5: Verification

1. Run all Python tests.
2. Run TypeScript type checking and production build.
3. Run Rust tests/checks.
4. Verify `chat.py` line count and inspect the final diff.
5. Run a real sidecar conversation with uploaded document plus historical generated artifact using an isolated database copy.

