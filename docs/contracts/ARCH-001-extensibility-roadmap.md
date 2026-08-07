# ARCH-001 — Extensibility Roadmap

| | |
|---|---|
| **Author** | Architect (Opus 5) |
| **Status** | Gate 0 — direction, not yet specified for build |
| **Date** | 2026-08-06 |

Not for implementation. This exists so that work done now does not foreclose these
capabilities, and so the Developer understands where the seams are.

## Governing principle

We are a fork tracking an upstream that ships ~4 commits/day. **Every capability below
should be built at an extension point, not by modifying core.** A feature implemented as
a plugin costs nothing at merge time. The same feature patched into `tool_service.py`
(261 upstream commits/year) is a permanent tax.

When the Developer proposes an approach, the first question is: *does this land in a
plugin, or does it fork core?* If it forks core, it needs architect sign-off and a
recorded reason.

---

## Capability 1 — Full-fidelity tool call visibility

**Requirement.** When a Voice AI or any LLM agent calls tools, see every call in detail:
what was called, with what arguments, what came back, where it routed, how failures were
handled.

### What exists today

| Mechanism | What it captures | Gap |
|---|---|---|
| `tool_metrics` table (`db.py`) | `tool_id`, `timestamp`, `response_time`, `is_success`, `error_message` | No arguments, no results. Timing only. |
| `ObservabilityService.trace_tool_invocation()` | Arguments, plus `status_code` and `response_size` for results | **Redacts** any argument key matching `password\|token\|key\|secret`. Does not store the result body. |
| Spans / traces | Hierarchy, timing, attributes | Same redaction; payloads absent |
| Plugin hooks (`tool_pre_invoke` / `tool_post_invoke`) | **Full payload, both directions** | Nothing currently writes them to durable storage |

So the data you want is **visible at the plugin boundary but not persisted anywhere**.

### Recommended direction

A **capture plugin**, not a core change. It sits on `tool_pre_invoke`/`tool_post_invoke`,
where full request and response payloads are already available, and writes them to a
dedicated store.

Three properties it must have from day one, even on a dev box:

1. **Redaction is configurable, not removed.** You are right that a local dev box has no
   PII concern. That will not hold once this touches a real CRM. Build the switch now —
   `full_capture: true` in dev, field-level policy in production — rather than
   retrofitting redaction later, which never happens cleanly.
2. **Correlation.** Every record carries the `correlation_id` already flowing through
   `CorrelationIDMiddleware`, so one agent turn can be reconstructed across many tool
   calls.
3. **Separate write path.** Follow the existing observability pattern (independent
   session, best-effort commit — see AGENTS.md "Observability Transaction Behavior"), so
   capture failures never fail the tool call.

### Open decisions for a future Gate 1

- Storage: reuse the observability tables, or a dedicated append-only store?
- Retention and volume: full payload capture on a busy gateway is expensive.
- Whether replay ("run this exact call again") is in scope — it changes the schema.

---

## Capability 2 — Routing intelligence across multiple backends

**Requirement.** Three CRMs behind the gateway. An agent calls "get customer details".
Which CRM holds that customer? Where does that intelligence live?

### What exists today — and why your assessment is correct

Tools are namespaced on registration as `{gateway_slug}{separator}{tool_name}`
(`db.py:3406`). Three CRMs therefore surface as **three distinct tools**:

```
salesforce-get-customer
hubspot-get-customer
zoho-get-customer
```

The gateway routes by `gateway_id` — a lookup of *where a tool is registered*, not a
decision about *which system holds an entity*. There is no resolution layer. The
selection burden falls entirely on the LLM, which has no basis to choose correctly.

**This is the single largest architectural gap in the product for your use case.** It is
not a bug in the gateway; the capability was never in scope upstream.

### The shape of the problem

This is entity resolution / system-of-record routing — a data problem wearing a routing
costume. Three viable patterns, in ascending cost:

| Pattern | How it decides | Good when | Cost |
|---|---|---|---|
| **Deterministic rules** | Attribute on the request picks the backend (region, tenant, ID prefix) | Ownership is structurally knowable | Low. Config, not infrastructure. |
| **Scatter–gather** | Query all backends, merge, return best or all | Small backend count, tolerant latency, no clean partition | Medium. N× load, needs merge and conflict policy. |
| **Resolution index** | A maintained map of entity key → system of record | Genuine MDM need, overlapping records | High. It is a new stateful system with its own sync and staleness problems. |

### Recommended direction

Expose **one logical tool** (`get-customer`) that fronts the three physical ones, with
resolution behind it. That keeps the agent's tool list clean and puts the intelligence
where it can be tested independently of the model.

Start with deterministic rules and fall back to scatter–gather. **Do not start with a
resolution index** — it is the correct end state for a real MDM problem but the wrong
place to begin, because you cannot yet know whether your partition is clean.

Critically: whatever the strategy, the **resolution decision must be recorded by
Capability 1**. "Which CRM did it choose, and why" is exactly the visibility being
asked for, and it is worthless if the routing layer is a black box.

### Dependency

This depends on Capability 3 — a logical tool fronting physical tools *is* a composite
tool. Sequence accordingly.

---

## Capability 3 — Composite tools

**Requirement.** Compose multiple underlying tools into unified tools.

### What exists today

- **Virtual servers** group existing tools into a custom MCP endpoint. Grouping and
  presentation, not composition — no data flows between tools.
- **`plugin_chain_pre` / `plugin_chain_post`** (REST tools only) run plugins around a
  single invocation. Middleware, not orchestration.
- **`mcpgateway/toolops/`** — an ALTK service. Worth the Developer investigating whether
  it already provides a composition primitive before anything new is designed.

No mechanism today takes tool A's output and feeds it to tool B.

### Recommended direction

A composite tool is: a declared input schema, a sequence or graph of underlying calls,
a mapping between steps, and an output projection. It should be **declarative and
stored**, not code — so composites are configuration rather than a fork of core.

Design constraints to hold from the start:

- **Failure semantics are the hard part**, not the happy path. Step 3 of 5 fails — is
  the composite atomic, partial, or compensating? Decide before building.
- **Composites must be observable per step.** A composite that reports only its final
  result destroys the visibility of Capability 1.
- **Guard recursion.** Composites calling composites needs a depth limit, or a
  malformed definition takes the gateway down.

### Sequencing

```
Capability 1 (visibility)
        │
        ├──────────────► Capability 3 (composition)
                                │
                                ▼
                         Capability 2 (routing)
```

Visibility first: it is standalone, immediately useful, and it is the instrument you
need to debug the other two. Composition next, because routing is a special case of it.
Routing last, when there is real data about how the backends actually partition.

---

## What this means for work happening now

CONTRACT-001 (brand migration) touches none of these paths. No conflict.

The one forward-looking constraint on current work: **do not spread hardcoded brand
strings into service code**. Prefer `settings.app_name`. When these capabilities add
surfaces — a capture UI, a composite editor — they should inherit the brand rather than
restate it.
