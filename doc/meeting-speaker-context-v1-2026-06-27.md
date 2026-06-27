# Meeting Speaker Context V1

## Scope

This slice introduces the backend entry point for future meeting LLM speakers without
turning the whole meeting into an all-agent LLM loop.

## Runtime Boundary

- `MeetingSpeakerSelector` selects speakers after a valid `meeting_ask`.
- V1 only selects the named NPC from the ask action.
- The selector enforces the active meeting participant boundary and caps the result to
  at most two speakers.
- `MeetingContextBuilder` builds a speaker-scoped context for the selected NPC.

## Context Boundary

The speaker context contains only:

- public `meeting.message.posted` records for the active meeting;
- evidence that has already been posted into the meeting as public evidence;
- memory snapshots visible to the selected NPC.

The context builder does not read global truth, `case.world_info`, or other NPC private
memory. It also ignores `meeting.message.proposed` records when building the public
meeting transcript.

## Event Flow

`meeting_ask` now follows this structure:

1. RuleEngine records the player's public meeting question as `meeting.message.posted`.
2. ActionService selects the named NPC and builds speaker context.
3. Deterministic V1 speaker text is recorded as `meeting.message.proposed`.
4. RuleEngine records the accepted public answer as `meeting.message.posted`.

The deterministic text remains a placeholder. The proposed event now carries reference
ids for public meeting messages, public evidence, and visible memory ids so a future LLM
speaker and Narrative Director validation pass can use the same boundary without
changing the public posted-message contract.
