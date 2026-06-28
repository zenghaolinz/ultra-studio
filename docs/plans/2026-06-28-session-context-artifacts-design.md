# Session Context and General Artifact Design

## Decision

The active agent runtime owns only conversation-scoped context. It must not read persona rows, the global memory map, long-term-memory files, activated memory, or recall/save-memory tools. Existing memory APIs and stored data remain available for backward compatibility, but they are outside the active runtime dependency graph.

Conversation history in `stm_entries` is retained because it is message history scoped by `conversation_id`, not global memory.

## Context boundary

`services/agent_context.py` builds runtime messages from:

1. A static Ultra Studio system contract.
2. Recent visible messages from the current conversation only.
3. The current user message and attachment paths.
4. Resolved conversation artifacts injected by `agent_runs.py`.

It never queries `persona`, loads the memory map, or exposes memory tools. Tool capability selection is deterministic from request text, current attachments, and resolved artifact kinds.

## General artifact model

The existing `conversation_artifacts` table remains the source of truth. The `kind` field becomes an open classifier with these runtime values:

- `image`, `document`, `code`, `audio`, `video`, `model`, `archive`, `file`

The existing transport field `image_paths` remains accepted because the desktop client already uses it for every attachment type. Internally it is treated as generic attachment paths, and new code uses attachment-oriented names.

Artifacts preserve source and provenance: uploaded files link to a user message; generated files link to a generation task; tool outputs may link to a tool call.

## Resolution

Resolution is deterministic and conversation-local. It recognizes source (`uploaded`, `generated`), kind (`PDF/document`, code, video, model, image, file), ordinal (`first`, `second`, Chinese equivalents), and recency references (`this file`, `above document`, `previously generated`). Mixed references may resolve one latest artifact per requested source or kind. Missing local paths are excluded.

The injected context contains exact paths and provenance only. File contents are not inserted automatically; the model must use `read_document` or related tools, which avoids prompt bloat and preserves a clear trust boundary.

## Failure and compatibility behavior

- Unknown extensions are recorded as `file` instead of silently dropped.
- Missing paths are not registered or resolved.
- Text-only models receive attachment paths but not image bytes.
- Existing image behavior and database rows remain compatible.
- Global-memory routes and data are not deleted in this change; isolation is enforced by imports, runtime behavior, and tests.

