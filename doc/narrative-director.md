# Narrative Director

The current Narrative Director is a minimal spoiler-safety layer. It validates
NPC speech before it can be written as an `npc.replied` event. It does not
advance phase or complete beats; those remain owned by `narrative_rules.yaml`
and `RuleTriggerSystem`.

## Configuration Source

Forbidden facts are authored in each case package's `forbidden_facts.yaml`.

Each forbidden fact contains:

- `id`: stable forbidden fact identifier
- `text`: internal fact description
- `blocked_terms`: terms that trigger blocking before reveal
- `reveal_phase`: phase where this fact may be spoken

Forbidden fact text and blocked terms are internal safety configuration. They
must not appear in `StateSummary`, `AgentContext`, or `player_journey.md`.

## Current Validation

`NarrativeDirector.validate(case, narrative, intent)` scans `intent.speech`.
If the speech contains a forbidden fact's `blocked_terms` before that fact's
`reveal_phase`, the Director rejects the reply.

When blocked:

- `npc.replied` is not written.
- `director.blocked` is written.
- the response returns safe speech.
- `ActionResponse.accepted=false`.

`director.blocked` may include the blocked fact id for audit, but it must not
include forbidden fact text or blocked terms.

## Character Private Disclosure Boundary

Character `private` data is the target NPC's own non-public perspective. It is
not hidden from the NPC itself. The target NPC always knows its own private
goals, secrets, and knowledge.

The runtime restriction is about outward speech, public projection, other NPC
visibility, and authoritative state mutation. `private` is not a permanent
speech ban, and it is not the same as `forbidden_facts`.

Character Inner Context v0 passes a target-only controlled self view into
`AgentContext.inner_context`. It does not pass another NPC's private data and
does not write private data into public runtime outputs. Outward expression must
still pass Narrative Director validation.

Future Director checks should verify whether generated speech:

- reveals a locked forbidden fact
- exceeds the disclosure mode selected by `DisclosurePolicy`
- quotes raw private content when only evasion, hinting, or partial disclosure
  is allowed
- contradicts case anchors, unlocked player knowledge, or narrative phase
  constraints
- exposes one NPC's private data to another NPC without an allowed public event

## Rule Engine Boundary

Narrative Director controls whether speech is safe to emit. It does not make
state changes authoritative.

Rule Engine remains responsible for deciding whether
`AgentIntent.proposed_actions` become real `WorldEvent` records. Knowing private
information never gives an NPC permission to directly mutate world state, clue
state, relationship state, memory snapshots, or narrative phase.

## Current Limits

Current v0 only performs term-based forbidden fact checks over
`AgentIntent.speech`.

It does not yet perform semantic spoiler detection, full disclosure policy
evaluation, multi-hop contradiction checks, or private-item redaction beyond the
current deterministic fallback behavior. Those belong to future
`DisclosurePolicy` enforcement work.
