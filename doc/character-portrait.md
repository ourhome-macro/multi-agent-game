# Private Character Impression v0

Private Character Impression v0 adds subjective NPC cognition about the player.
It is also called a character portrait in design notes, but the runtime event
name is `character_impression.updated`.

## Definitions

- Character Card: author-defined true character setup.
- CharacterInnerContext: target NPC's controlled private cognition input.
- `private.goals`: what I want.
- `private.secrets`: what I am hiding.
- `private.knowledge`: what facts I know from my own perspective.
- `inner_portraits`: how I see someone else.
- Relationship Metrics: numeric social state such as `trust`, `suspicion`, and
  `fear`.
- Character Impression: one observer's subjective judgment, bias, hypothesis,
  trust boundary, alliance potential, and threat sense about one target.
- Memory Snapshot: runtime-owned important experience derived from events.
- Narrative Rules: phases, beats, and resolution conditions.
- RuleEngine: authority for accepted state changes.
- NarrativeDirector: authority for output safety and spoiler control.

## Boundary

A character impression is not a character-card truth. It does not say who the
target really is. It records how `observer_id` currently interprets `target_id`.

V0 only supports NPC -> player impressions:

```text
session.character_impressions[npc_id]["player"]
```

The runtime does not support player -> NPC impressions or NPC -> NPC impressions
yet.

## Model

`CharacterImpression` contains:

- `observer_id`
- `target_id`
- `personality_impression`
- `perceived_motive`
- `suspected_knowledge_refs`
- `suspicious_points`
- `trust_boundary`
- `alliance_potential`
- `threat_level`
- `manipulation_risk`
- `usefulness`
- `tags`
- `confidence`
- `source_event_ids`
- `last_updated_event_id`

The text fields must be generated from safe runtime signals. They must not copy
forbidden fact text, blocked terms, raw character private secrets, or solution
claim configuration.

## Derivation

V0 impressions are derived by runtime code, not by LLM output. The derivation
sources are:

- `player.asked_about`
- `player.presented_clue`
- `player.accused`
- `relationship.threshold.crossed`
- `director.blocked`
- `accusation.evaluated`

Each update writes a `character_impression.updated` event. Replay applies that
event directly and does not re-run impression derivation.

## Agent Input

`CharacterInnerContext.inner_portraits` exposes only the current target NPC's own
impressions. If the butler has an impression of the player, the butler can see it
in `inner_portraits`; another NPC cannot.

`AgentContext.recent_events` filters out `character_impression.updated` events so
one NPC cannot see another NPC's private portrait through the recent-event feed.

LLM agents may consume `inner_portraits`, but they cannot directly modify
`SessionState`. Any future impression write must still be a runtime-derived
`character_impression.updated` event.

## Output Safety

Impressions are private cognition. They must not be exposed through:

- `StateSummary`
- `player_journey.md` raw text
- another NPC's `AgentContext`
- `AgentIntent.proposed_actions`

Player journey Markdown may mention that a private impression changed, but it
must not print `personality_impression`, `perceived_motive`, or `trust_boundary`
text.

NarrativeDirector still validates outward speech. RuleEngine still validates
state-changing proposed actions.
