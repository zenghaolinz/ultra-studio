# Conversation Artifact Ledger Design

## Decision

Ultra Studio will persist conversation-scoped media as typed artifacts instead of recovering paths from assistant prose. The ledger is a materialized index over user attachments, tool outputs, and asynchronous generation task outputs.

## Data model

`conversation_artifacts` stores a stable id, conversation id, optional message/tool/task provenance, kind, source, path, prompt, status, sequence, and timestamps. A unique provenance/path key makes event replay idempotent. Conversation deletion cascades to artifacts; files on disk are not deleted.

Sources are `uploaded`, `generated`, and `tool`. Status is `available`, `pending`, or `error`. Only available artifacts are eligible for model references.

## Data flow

1. A chat request with `image_paths` saves the visible user message, then records each existing image as `uploaded` in request order.
2. Generation tools already attach `conversation_id` to queue tasks. When a task reaches `success`, its output paths are recorded as `generated`, linked to the task id and prompt. Sync and async task updates use the same projection helper.
3. Before a model run, the resolver loads recent available artifacts and deterministically interprets source and ordinal phrases.
4. The runtime injects a compact model-visible block containing artifact ids, source, ordinal, and canonical path. The current user message also receives an explicit resolution block for unambiguous references.

## Resolution rules

- “上面这张图” / “这张图” resolves to the latest available image.
- “我上传的图片” resolves to the latest uploaded image.
- “之前生成的图片” resolves to the latest generated image.
- Ordinals apply within the requested source; otherwise within all matching images.
- A request mentioning both uploaded and generated images returns both in source order.
- Missing or ambiguous references are not converted to invented paths; the context lists candidates so the model can ask the user.

## Failure handling

Artifact projection is idempotent and must not make generation task completion fail. Projection failures are logged without paths beyond the already local application log policy. Missing files are excluded from reference resolution. No API keys or image bytes are stored in the ledger.

## Alternatives considered

Parsing STM text was rejected because formatting and localization change. Typed message parts alone were rejected because asynchronous task outputs appear after the originating model turn. A standalone path table without provenance was rejected because it cannot distinguish uploads from generated assets.

