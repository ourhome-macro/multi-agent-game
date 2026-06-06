Return a single JSON object and no markdown. The top-level keys must be exactly:

- speech
- intent
- emotional_shift
- proposed_actions
- memory_refs
- disclosure_claims

speech must be a string.

intent must be one of:

- answer
- conceal
- lie
- refuse
- probe
- panic

emotional_shift must be an object. Use {} when there is no shift.

proposed_actions must be an array. Use [] when there is no allowed state
proposal. proposed_actions may only contain:

- clue.discover with clue_id
- relationship.change with source_id, target_id, and numeric deltas for trust,
  suspicion, fear, intimacy, hostility

memory_refs must be an array of strings.

disclosure_claims must be an array. Each item must have:

- world_info_id
- mode
- tactic
- source_refs
- claim_refs

mode must be one of none, deny, deflect, hint, partial, full. Never use full.
tactic must be null or one of answer_adjacent_truth, shift_focus,
counter_question, qualify_certainty, emotional_screen, silence.

