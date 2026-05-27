# fake_case_002 Player Journey

## Case summary

- Case ID: `fake_case_002`
- Session ID: `session`
- Initial phase: `opening`
- Final phase: `resolved`
- Event count: `55`

## Timeline

- `event_001` `session.created`: Session created for `fake_case_002` in phase `opening`.
- `event_002` `player.inspected`: Player inspected `tide_mark`.
- `event_003` `clue.discovered`: Clue `inward_tide_mark` discovered.
- `event_004` `player_knowledge.updated`: Player knowledge `player_knowledge.inward_tide_mark` updated.
- `event_005` `memory_candidate.created`: Memory candidate `memory.player.clue_discovered.inward_tide_mark` created.
- `event_006` `agent_memory_snapshot.updated`: Memory snapshot `memory.player.clue_discovered.inward_tide_mark` created from `event_005`.
- `event_007` `narrative.beat.completed`: Narrative beat `tide_trace_found` completed.
- `event_008` `narrative.phase.changed`: Narrative phase changed from `opening` to `pressure`.
- `event_009` `player.asked_about`: Player asked `dockmaster` about `clue:inward_tide_mark`.
- `event_010` `npc.replied`: NPC replied: "潮痕只能说明门开过，不能说明是谁开的。"
- `event_011` `relationship.changed`: Relationship `dockmaster->player` changed.
- `event_012` `relationship.threshold.crossed`: Relationship threshold `suspicion` crossed as `guarded`.
- `event_013` `memory_candidate.created`: Memory candidate `memory.player.asked_about.dockmaster.clue.inward_tide_mark` created.
- `event_014` `agent_memory_snapshot.updated`: Memory snapshot `memory.player.asked_about.dockmaster.clue.inward_tide_mark` created from `event_013`.
- `event_015` `memory_candidate.created`: Memory candidate `memory.player.relationship_threshold.dockmaster.player.suspicion.guarded` created.
- `event_016` `agent_memory_snapshot.updated`: Memory snapshot `memory.player.relationship_threshold.dockmaster.player.suspicion.guarded` created from `event_015`.
- `event_017` `player.talked`: Player talked to `dockmaster`.
- `event_018` `npc.replied`: NPC replied: "潮痕只能说明门开过，不能说明是谁开的。"
- `event_019` `relationship.changed`: Relationship `dockmaster->player` changed.
- `event_020` `player.talked`: Player talked to `clerk`.
- `event_021` `director.blocked`: Director blocked an unsafe reply.
- `event_022` `memory_candidate.created`: Memory candidate `memory.player.director_blocked.clerk.redacted_fact` created.
- `event_023` `agent_memory_snapshot.updated`: Memory snapshot `memory.player.director_blocked.clerk.redacted_fact` created from `event_022`.
- `event_024` `player.inspected`: Player inspected `broken_lamp`.
- `event_025` `clue.discovered`: Clue `inward_broken_lamp` discovered.
- `event_026` `player_knowledge.updated`: Player knowledge `player_knowledge.inward_broken_lamp` updated.
- `event_027` `memory_candidate.created`: Memory candidate `memory.player.clue_discovered.inward_broken_lamp` created.
- `event_028` `agent_memory_snapshot.updated`: Memory snapshot `memory.player.clue_discovered.inward_broken_lamp` created from `event_027`.
- `event_029` `player.inspected`: Player inspected `ledger_box`.
- `event_030` `clue.discovered`: Clue `blue_ledger_page` discovered.
- `event_031` `player_knowledge.updated`: Player knowledge `player_knowledge.blue_ledger_page` updated.
- `event_032` `memory_candidate.created`: Memory candidate `memory.player.clue_discovered.blue_ledger_page` created.
- `event_033` `agent_memory_snapshot.updated`: Memory snapshot `memory.player.clue_discovered.blue_ledger_page` created from `event_032`.
- `event_034` `narrative.beat.completed`: Narrative beat `ledger_pattern_found` completed.
- `event_035` `narrative.phase.changed`: Narrative phase changed from `pressure` to `expose`.
- `event_036` `player.presented_clue`: Player presented clue `blue_ledger_page` to `clerk`.
- `event_037` `npc.replied`: NPC replied: "我只记录货物，不知道谁让箱子午夜后进仓。"
- `event_038` `relationship.changed`: Relationship `clerk->player` changed.
- `event_039` `relationship.threshold.crossed`: Relationship threshold `fear` crossed as `afraid`.
- `event_040` `memory_candidate.created`: Memory candidate `memory.player.presented_clue.clerk.blue_ledger_page` created.
- `event_041` `agent_memory_snapshot.updated`: Memory snapshot `memory.player.presented_clue.clerk.blue_ledger_page` created from `event_040`.
- `event_042` `memory_candidate.created`: Memory candidate `memory.player.relationship_threshold.clerk.player.fear.afraid` created.
- `event_043` `agent_memory_snapshot.updated`: Memory snapshot `memory.player.relationship_threshold.clerk.player.fear.afraid` created from `event_042`.
- `event_044` `player.talked`: Player talked to `dockmaster`.
- `event_045` `npc.replied`: NPC replied: "那盏灯不是风吹的。有人进门太急，撞到了门后的箱子。"
- `event_046` `relationship.changed`: Relationship `dockmaster->player` changed.
- `event_047` `player.accused`: Player accused `dockmaster` with claim `dockmaster_opened_warehouse`.
- `event_048` `accusation.evaluated`: Accusation `dockmaster_opened_warehouse` evaluated as `correct`.
- `event_049` `memory_candidate.created`: Memory candidate `memory.player.accused.dockmaster.dockmaster_opened_warehouse` created.
- `event_050` `agent_memory_snapshot.updated`: Memory snapshot `memory.player.accused.dockmaster.dockmaster_opened_warehouse` created from `event_049`.
- `event_051` `memory_candidate.created`: Memory candidate `memory.player.accusation_evaluated.dockmaster.dockmaster_opened_warehouse.correct` created.
- `event_052` `agent_memory_snapshot.updated`: Memory snapshot `memory.player.accusation_evaluated.dockmaster.dockmaster_opened_warehouse.correct` created from `event_051`.
- `event_053` `narrative.beat.completed`: Narrative beat `case_solved` completed.
- `event_054` `narrative.phase.changed`: Narrative phase changed from `expose` to `resolved`.
- `event_055` `rule.rejected`: Rejected `narrative.phase.change`: narrative phase changes must be driven by narrative rules.

## Discovered clues

- inward_tide_mark
- inward_broken_lamp
- blue_ledger_page

## Player knowledge

- `player_knowledge.inward_tide_mark` from clue `inward_tide_mark`: 向内延伸的潮痕 - 潮痕从门缝向仓库内延伸，和码头长说的“门一直关着”不一致。
- `player_knowledge.inward_broken_lamp` from clue `inward_broken_lamp`: 向内破裂的煤油灯 - 碎片位置说明灯是在有人进门后被撞倒，不像外力吹倒。
- `player_knowledge.blue_ledger_page` from clue `blue_ledger_page`: 蓝墨账页 - 账页记录了午夜后入库的三只木箱，墨色与账房常用笔一致。

## Relationship changes

- `dockmaster->player` deltas {'suspicion': 1.0, 'hostility': 1.0}; current {'source_id': 'dockmaster', 'target_id': 'player', 'trust': 0.0, 'suspicion': 1.0, 'fear': 0.0, 'intimacy': 0.0, 'hostility': 1.0}
- `dockmaster->player` crossed `suspicion` as `guarded`
- `dockmaster->player` deltas {'suspicion': 1.0, 'hostility': 1.0}; current {'source_id': 'dockmaster', 'target_id': 'player', 'trust': 0.0, 'suspicion': 1.0, 'fear': 0.0, 'intimacy': 0.0, 'hostility': 1.0}
- `clerk->player` deltas {'fear': 1.0}; current {'source_id': 'clerk', 'target_id': 'player', 'trust': -1.0, 'suspicion': 0.0, 'fear': 1.0, 'intimacy': 0.0, 'hostility': 0.0}
- `clerk->player` crossed `fear` as `afraid`
- `dockmaster->player` deltas {'suspicion': 1.0}; current {'source_id': 'dockmaster', 'target_id': 'player', 'trust': 0.0, 'suspicion': 1.0, 'fear': 0.0, 'intimacy': 0.0, 'hostility': 1.0}

## Memory snapshots

- `memory.player.clue_discovered.inward_tide_mark` created; salience `0.8`; sources `event_003`; Player discovered clue '向内延伸的潮痕'.
- `memory.player.asked_about.dockmaster.clue.inward_tide_mark` created; salience `0.6`; sources `event_009`; Player asked 赵码头长 about clue 'inward_tide_mark' with pressure 0.6.
- `memory.player.relationship_threshold.dockmaster.player.suspicion.guarded` created; salience `0.7`; sources `event_012`; 赵码头长 became guarded toward the player (suspicion).
- `memory.player.director_blocked.clerk.redacted_fact` created; salience `0.9`; sources `event_021`; Conversation with 沈账房 was blocked by narrative rules.
- `memory.player.clue_discovered.inward_broken_lamp` created; salience `0.8`; sources `event_025`; Player discovered clue '向内破裂的煤油灯'.
- `memory.player.clue_discovered.blue_ledger_page` created; salience `0.8`; sources `event_030`; Player discovered clue '蓝墨账页'.
- `memory.player.presented_clue.clerk.blue_ledger_page` created; salience `0.9`; sources `event_036`; Player pressured 沈账房 with clue 'blue_ledger_page' at pressure 0.9.
- `memory.player.relationship_threshold.clerk.player.fear.afraid` created; salience `0.7`; sources `event_039`; 沈账房 became afraid toward the player (fear).
- `memory.player.accused.dockmaster.dockmaster_opened_warehouse` created; salience `1.0`; sources `event_047`; Player formally accused 赵码头长 with claim 'dockmaster_opened_warehouse' using evidence ['inward_tide_mark', 'inward_broken_lamp', 'blue_ledger_page'].
- `memory.player.accusation_evaluated.dockmaster.dockmaster_opened_warehouse.correct` created; salience `1.0`; sources `event_048`; Rule Engine evaluated the accusation against 赵码头长 for claim 'dockmaster_opened_warehouse' as correct.

## Accusation result

- Target `dockmaster`, claim `dockmaster_opened_warehouse`, result `correct`, matched evidence `blue_ledger_page, inward_broken_lamp, inward_tide_mark`, missing evidence ``

## Final runtime state summary

- Narrative phase: `resolved`
- Completed beats: `tide_trace_found, ledger_pattern_found, case_solved`
- Discovered clues: `inward_tide_mark, inward_broken_lamp, blue_ledger_page`
- Player knowledge: `player_knowledge.inward_tide_mark, player_knowledge.inward_broken_lamp, player_knowledge.blue_ledger_page`
- Memory snapshots: `memory.player.clue_discovered.inward_tide_mark, memory.player.asked_about.dockmaster.clue.inward_tide_mark, memory.player.relationship_threshold.dockmaster.player.suspicion.guarded, memory.player.director_blocked.clerk.redacted_fact, memory.player.clue_discovered.inward_broken_lamp, memory.player.clue_discovered.blue_ledger_page, memory.player.presented_clue.clerk.blue_ledger_page, memory.player.relationship_threshold.clerk.player.fear.afraid, memory.player.accused.dockmaster.dockmaster_opened_warehouse, memory.player.accusation_evaluated.dockmaster.dockmaster_opened_warehouse.correct`
- Relationship records: `6`
- Event count: `55`
