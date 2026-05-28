# fake_case_002 Player Journey

## Case summary

- Case ID: `fake_case_002`
- Session ID: `session`
- Initial phase: `opening`
- Final phase: `resolved`
- Event count: `62`

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
- `event_013` `character_impression.updated`: Private character impression updated.
- `event_014` `memory_candidate.created`: Memory candidate `memory.player.asked_about.dockmaster.clue.inward_tide_mark` created.
- `event_015` `agent_memory_snapshot.updated`: Memory snapshot `memory.player.asked_about.dockmaster.clue.inward_tide_mark` created from `event_014`.
- `event_016` `character_impression.updated`: Private character impression updated.
- `event_017` `memory_candidate.created`: Memory candidate `memory.player.relationship_threshold.dockmaster.player.suspicion.guarded` created.
- `event_018` `agent_memory_snapshot.updated`: Memory snapshot `memory.player.relationship_threshold.dockmaster.player.suspicion.guarded` created from `event_017`.
- `event_019` `player.talked`: Player talked to `dockmaster`.
- `event_020` `npc.replied`: NPC replied: "潮痕只能说明门开过，不能说明是谁开的。"
- `event_021` `relationship.changed`: Relationship `dockmaster->player` changed.
- `event_022` `player.talked`: Player talked to `clerk`.
- `event_023` `director.blocked`: Director blocked an unsafe reply.
- `event_024` `character_impression.updated`: Private character impression updated.
- `event_025` `memory_candidate.created`: Memory candidate `memory.player.director_blocked.clerk.redacted_fact` created.
- `event_026` `agent_memory_snapshot.updated`: Memory snapshot `memory.player.director_blocked.clerk.redacted_fact` created from `event_025`.
- `event_027` `player.inspected`: Player inspected `broken_lamp`.
- `event_028` `clue.discovered`: Clue `inward_broken_lamp` discovered.
- `event_029` `player_knowledge.updated`: Player knowledge `player_knowledge.inward_broken_lamp` updated.
- `event_030` `memory_candidate.created`: Memory candidate `memory.player.clue_discovered.inward_broken_lamp` created.
- `event_031` `agent_memory_snapshot.updated`: Memory snapshot `memory.player.clue_discovered.inward_broken_lamp` created from `event_030`.
- `event_032` `player.inspected`: Player inspected `ledger_box`.
- `event_033` `clue.discovered`: Clue `blue_ledger_page` discovered.
- `event_034` `player_knowledge.updated`: Player knowledge `player_knowledge.blue_ledger_page` updated.
- `event_035` `memory_candidate.created`: Memory candidate `memory.player.clue_discovered.blue_ledger_page` created.
- `event_036` `agent_memory_snapshot.updated`: Memory snapshot `memory.player.clue_discovered.blue_ledger_page` created from `event_035`.
- `event_037` `narrative.beat.completed`: Narrative beat `ledger_pattern_found` completed.
- `event_038` `narrative.phase.changed`: Narrative phase changed from `pressure` to `expose`.
- `event_039` `player.presented_clue`: Player presented clue `blue_ledger_page` to `clerk`.
- `event_040` `npc.replied`: NPC replied: "我只记录货物，不知道谁让箱子午夜后进仓。"
- `event_041` `relationship.changed`: Relationship `clerk->player` changed.
- `event_042` `relationship.threshold.crossed`: Relationship threshold `fear` crossed as `afraid`.
- `event_043` `character_impression.updated`: Private character impression updated.
- `event_044` `memory_candidate.created`: Memory candidate `memory.player.presented_clue.clerk.blue_ledger_page` created.
- `event_045` `agent_memory_snapshot.updated`: Memory snapshot `memory.player.presented_clue.clerk.blue_ledger_page` created from `event_044`.
- `event_046` `character_impression.updated`: Private character impression updated.
- `event_047` `memory_candidate.created`: Memory candidate `memory.player.relationship_threshold.clerk.player.fear.afraid` created.
- `event_048` `agent_memory_snapshot.updated`: Memory snapshot `memory.player.relationship_threshold.clerk.player.fear.afraid` created from `event_047`.
- `event_049` `player.talked`: Player talked to `dockmaster`.
- `event_050` `npc.replied`: NPC replied: "那盏灯不是风吹的。有人进门太急，撞到了门后的箱子。"
- `event_051` `relationship.changed`: Relationship `dockmaster->player` changed.
- `event_052` `player.accused`: Player accused `dockmaster` with claim `dockmaster_opened_warehouse`.
- `event_053` `accusation.evaluated`: Accusation `dockmaster_opened_warehouse` evaluated as `correct`.
- `event_054` `character_impression.updated`: Private character impression updated.
- `event_055` `memory_candidate.created`: Memory candidate `memory.player.accused.dockmaster.dockmaster_opened_warehouse` created.
- `event_056` `agent_memory_snapshot.updated`: Memory snapshot `memory.player.accused.dockmaster.dockmaster_opened_warehouse` created from `event_055`.
- `event_057` `character_impression.updated`: Private character impression updated.
- `event_058` `memory_candidate.created`: Memory candidate `memory.player.accusation_evaluated.dockmaster.dockmaster_opened_warehouse.correct` created.
- `event_059` `agent_memory_snapshot.updated`: Memory snapshot `memory.player.accusation_evaluated.dockmaster.dockmaster_opened_warehouse.correct` created from `event_058`.
- `event_060` `narrative.beat.completed`: Narrative beat `case_solved` completed.
- `event_061` `narrative.phase.changed`: Narrative phase changed from `expose` to `resolved`.
- `event_062` `rule.rejected`: Rejected `narrative.phase.change`: narrative phase changes must be driven by narrative rules.

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
- `memory.player.director_blocked.clerk.redacted_fact` created; salience `0.9`; sources `event_023`; Conversation with 沈账房 was blocked by narrative rules.
- `memory.player.clue_discovered.inward_broken_lamp` created; salience `0.8`; sources `event_028`; Player discovered clue '向内破裂的煤油灯'.
- `memory.player.clue_discovered.blue_ledger_page` created; salience `0.8`; sources `event_033`; Player discovered clue '蓝墨账页'.
- `memory.player.presented_clue.clerk.blue_ledger_page` created; salience `0.9`; sources `event_039`; Player pressured 沈账房 with clue 'blue_ledger_page' at pressure 0.9.
- `memory.player.relationship_threshold.clerk.player.fear.afraid` created; salience `0.7`; sources `event_042`; 沈账房 became afraid toward the player (fear).
- `memory.player.accused.dockmaster.dockmaster_opened_warehouse` created; salience `1.0`; sources `event_052`; Player formally accused 赵码头长 with claim 'dockmaster_opened_warehouse' using evidence ['inward_tide_mark', 'inward_broken_lamp', 'blue_ledger_page'].
- `memory.player.accusation_evaluated.dockmaster.dockmaster_opened_warehouse.correct` created; salience `1.0`; sources `event_053`; Rule Engine evaluated the accusation against 赵码头长 for claim 'dockmaster_opened_warehouse' as correct.

## Accusation result

- Target `dockmaster`, claim `dockmaster_opened_warehouse`, result `correct`, matched evidence `blue_ledger_page, inward_broken_lamp, inward_tide_mark`, missing evidence ``

## Final runtime state summary

- Narrative phase: `resolved`
- Completed beats: `tide_trace_found, ledger_pattern_found, case_solved`
- Discovered clues: `inward_tide_mark, inward_broken_lamp, blue_ledger_page`
- Player knowledge: `player_knowledge.inward_tide_mark, player_knowledge.inward_broken_lamp, player_knowledge.blue_ledger_page`
- Memory snapshots: `memory.player.clue_discovered.inward_tide_mark, memory.player.asked_about.dockmaster.clue.inward_tide_mark, memory.player.relationship_threshold.dockmaster.player.suspicion.guarded, memory.player.director_blocked.clerk.redacted_fact, memory.player.clue_discovered.inward_broken_lamp, memory.player.clue_discovered.blue_ledger_page, memory.player.presented_clue.clerk.blue_ledger_page, memory.player.relationship_threshold.clerk.player.fear.afraid, memory.player.accused.dockmaster.dockmaster_opened_warehouse, memory.player.accusation_evaluated.dockmaster.dockmaster_opened_warehouse.correct`
- Relationship records: `6`
- Event count: `62`
