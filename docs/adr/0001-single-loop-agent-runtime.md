# ADR 0001: Replace Per-Message LLM Routing with a Single Agent Loop

- Status: Accepted
- Date: 2026-06-27
- Decision owners: Ultra Studio maintainers

## Context

The current streaming chat path performs a separate non-streaming LLM routing request before the primary model request. It then combines deterministic intent branches, native tool calling, textual DSML tool parsing, and several fallback paths. For ordinary chat this adds an entire model round trip before time-to-first-token (TTFT). The final model stream also buffers up to 512 characters while checking for textual tool syntax.

The result is high TTFT, duplicated decision-making, and an orchestration boundary spread across `sidecar/routes/chat.py` and many specialized helpers.

## Decision

Ultra Studio will use one primary model loop per natural-language turn. The model receives a policy-filtered set of structured tools and decides whether to emit text or tool calls. Tool results are returned to the same loop until it emits a final response or reaches a bounded stop condition.

Deterministic UI actions and confirmed operations may bypass model inference. Model selection, visible capabilities, and permissions remain deterministic runtime concerns. They are not delegated to a separate per-message LLM classifier.

The new runtime will live under `sidecar/agent_runtime/`. Existing document, filesystem, memory, MCP, and generation services remain authoritative domain services and are exposed through adapters. The legacy chat orchestration remains available only during migration and will be deleted after parity gates pass.

DSML parsing becomes a provider compatibility adapter used only for models without reliable native tool calling. Native-tool providers never buffer normal text for DSML detection.

## Consequences

### Positive

- Ordinary chat needs one model request and can forward the first model text delta immediately.
- Text and tool decisions share the same context and reasoning pass.
- Tool permissions, confirmation, retry bounds, and event emission become centralized and testable.
- `chat.py` becomes an HTTP/SSE adapter rather than an orchestration engine.

### Negative

- Tool schemas increase prompt size and must be filtered by capability profile.
- Provider differences require explicit adapters.
- Migration temporarily maintains two runtimes and a comparison harness.

## Rejected Alternatives

### Keep the LLM router and add a chat fast path

Rejected because it creates another classifier and preserves two competing decision systems. Misclassification would remain a correctness and maintenance problem.

### Only reduce the 512-character buffer

Rejected as the final architecture because it leaves the extra router model call and duplicated routing semantics intact.

### Embed OpenCode or OpenClaw

Rejected because Ultra Studio has domain-specific media queues, artifacts, desktop events, and local configuration. Their single-loop and policy patterns are adopted without importing their full runtime and operational surface.

## Acceptance Gates

- Ordinary chat performs one model call and emits the first text delta without application buffering.
- Native tool calls execute through one registry and bounded loop.
- Destructive tools are enforced by policy independently of model output.
- Image, video, and 3D tools enqueue work and return immediately.
- Run events expose phase timings, including TTFT.
- Legacy and new runtime replay tests meet the agreed response/tool parity suite before default cutover.
