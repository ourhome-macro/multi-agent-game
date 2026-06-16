# Mist Clock Manor NPC Skill Asset Landing

Date: 2026-06-16

## Scope

`cases/mist_clock_manor/npc_skills.yaml` now defines case-level NPC skill
boundaries for the first high-risk production interactions:

- `jiang_lock_boundary`: `jiang_yanhui` x `delayed_lock_marks`,
  `lock_test_scrap`.
- `jiang_capsule_boundary`: `jiang_yanhui` x `empty_capsules`,
  `capsule_powder_on_liner`.
- `qi_tape_boundary`: `qi_yan` x `echo_tape`, `ruolan_voice_tape`,
  `tape_splice_mark`.
- `lin_wine_boundary`: `lin_qichi` x `bitter_wine`, `sedative_bottle_label`.
- `shen_power_boundary`: `shen_zhaoye` x `cut_power_trace`, `backup_timer`,
  `breaker_sequence_tag`.
- `shen_study_lock_boundary`: `shen_zhaoye` x `delayed_lock_marks`,
  `lock_test_scrap`.
- `shen_old_case_boundary`: `shen_zhaoye` x `lake_death_clipping`,
  `incomplete_evidence_box`, `missing_visitor_log_page`.

## Boundary Rules

Each skill declares owner, triggers, unlock conditions, disclosure cap,
allowed tactics, memory policy, and proposed relationship delta caps. The
first production pass caps `max_mode` at `hint`, so NPCs can acknowledge
player-held evidence without directly admitting causal responsibility or
collapsing the shared death-chain mystery.

`safe_fragment_refs` are canonical
`world_info_id.safe_fragment:fragment_id` values sourced from
`world_info.yaml` claim-graph `safe_fragments`. Every referenced world info id
is also listed in `disclosure.world_info_ids`; CaseLoader validates existence
and binding.

## Verification

`tests/test_mist_clock_manor_npc_skills.py` verifies:

- CaseLoader loads the new main-case skill asset.
- Key high-risk actions select the expected skill through the real runtime
  context builder.
- `NpcSkillProjection` exposes ids, mode/tactic/action caps, and safe
  fragment refs without leaking WorldInfo body text, clue body text, safe
  fragment summaries, or character private summaries.
