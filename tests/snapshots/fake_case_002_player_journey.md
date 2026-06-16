# fake_case_002 Player Journey

## Case summary

- Case ID: `fake_case_002`
- Session ID: `session`
- Initial phase: `opening`
- Final phase: `resolved`
- Event count: `67`

## Timeline

- `event_001` `session.created`: Session created for `fake_case_002` in phase `opening`.
- `event_002` `player.inspected`: Player inspected `tide_mark`.
- `event_003` `clue.discovered`: Clue `inward_tide_mark` discovered.
- `event_004` `player_knowledge.updated`: Player knowledge `player_knowledge.warehouse_opened_after_tide` updated.
- `event_005` `memory_candidate.created`: Memory candidate `memory.player.clue_discovered.inward_tide_mark` created.
- `event_006` `agent_memory_snapshot.updated`: Memory snapshot `memory.player.clue_discovered.inward_tide_mark` create from `event_005`.
- `event_007` `narrative.beat.completed`: Narrative beat `tide_trace_found` completed.
- `event_008` `narrative.phase.changed`: Narrative phase changed from `opening` to `pressure`.
- `event_009` `player.asked_about`: Player asked `dockmaster` about `clue:inward_tide_mark`.
- `event_010` `npc.replied`: NPC replied: "潮痕只能说明门开过，不能说明是谁开的。"
- `event_011` `relationship.changed`: Relationship `dockmaster->player` changed.
- `event_012` `relationship.threshold.crossed`: Relationship threshold `suspicion` crossed as `guarded`.
- `event_013` `character_impression.updated`: Private character impression updated.
- `event_014` `character_fact_awareness.updated`: Private character fact awareness updated.
- `event_015` `memory_candidate.created`: Memory candidate `memory.player.asked_about.dockmaster.clue.inward_tide_mark` created.
- `event_016` `agent_memory_snapshot.updated`: Memory snapshot `memory.player.asked_about.dockmaster.clue.inward_tide_mark` create from `event_015`.
- `event_017` `character_impression.updated`: Private character impression updated.
- `event_018` `memory_candidate.created`: Memory candidate `memory.player.relationship_threshold.dockmaster.player.suspicion.guarded` created.
- `event_019` `agent_memory_snapshot.updated`: Memory snapshot `memory.player.relationship_threshold.dockmaster.player.suspicion.guarded` create from `event_018`.
- `event_020` `player.talked`: Player talked to `dockmaster`.
- `event_021` `npc.replied`: NPC replied: "潮痕只能说明门开过，不能说明是谁开的。"
- `event_022` `relationship.changed`: Relationship `dockmaster->player` changed.
- `event_023` `player.talked`: Player talked to `clerk`.
- `event_024` `director.blocked`: Director blocked an unsafe reply.
- `event_025` `character_impression.updated`: Private character impression updated.
- `event_026` `memory_candidate.created`: Memory candidate `memory.player.director_blocked.clerk.redacted_fact` created.
- `event_027` `agent_memory_snapshot.updated`: Memory snapshot `memory.player.director_blocked.clerk.redacted_fact` create from `event_026`.
- `event_028` `player.inspected`: Player inspected `broken_lamp`.
- `event_029` `clue.discovered`: Clue `inward_broken_lamp` discovered.
- `event_030` `player_knowledge.updated`: Player knowledge `player_knowledge.lamp_broken_from_inside_entry` updated.
- `event_031` `memory_candidate.created`: Memory candidate `memory.player.clue_discovered.inward_broken_lamp` created.
- `event_032` `agent_memory_snapshot.updated`: Memory snapshot `memory.player.clue_discovered.inward_broken_lamp` create from `event_031`.
- `event_033` `player.inspected`: Player inspected `ledger_box`.
- `event_034` `clue.discovered`: Clue `blue_ledger_page` discovered.
- `event_035` `player_knowledge.updated`: Player knowledge `player_knowledge.blue_ledger_records_midnight_boxes` updated.
- `event_036` `memory_candidate.created`: Memory candidate `memory.player.clue_discovered.blue_ledger_page` created.
- `event_037` `agent_memory_snapshot.updated`: Memory snapshot `memory.player.clue_discovered.blue_ledger_page` create from `event_036`.
- `event_038` `narrative.beat.completed`: Narrative beat `ledger_pattern_found` completed.
- `event_039` `narrative.phase.changed`: Narrative phase changed from `pressure` to `expose`.
- `event_040` `player.presented_clue`: Player presented clue `blue_ledger_page` to `clerk`.
- `event_041` `npc.replied`: NPC replied: "我只记录货物，不知道谁让箱子午夜后进仓。"
- `event_042` `relationship.changed`: Relationship `clerk->player` changed.
- `event_043` `relationship.threshold.crossed`: Relationship threshold `fear` crossed as `afraid`.
- `event_044` `character_impression.updated`: Private character impression updated.
- `event_045` `character_fact_awareness.updated`: Private character fact awareness updated.
- `event_046` `memory_candidate.created`: Memory candidate `memory.player.presented_clue.clerk.blue_ledger_page` created.
- `event_047` `agent_memory_snapshot.updated`: Memory snapshot `memory.player.presented_clue.clerk.blue_ledger_page` create from `event_046`.
- `event_048` `character_impression.updated`: Private character impression updated.
- `event_049` `memory_candidate.created`: Memory candidate `memory.player.relationship_threshold.clerk.player.fear.afraid` created.
- `event_050` `agent_memory_snapshot.updated`: Memory snapshot `memory.player.relationship_threshold.clerk.player.fear.afraid` create from `event_049`.
- `event_051` `player.talked`: Player talked to `dockmaster`.
- `event_052` `npc.replied`: NPC replied: "那盏灯不是风吹的。有人进门太急，撞到了门后的箱子。"
- `event_053` `relationship.changed`: Relationship `dockmaster->player` changed.
- `event_054` `player.accused`: Player accused `dockmaster` with claim `dockmaster_opened_warehouse`.
- `event_055` `accusation.evaluated`: Accusation `dockmaster_opened_warehouse` evaluated as `correct`.
- `event_056` `character_impression.updated`: Private character impression updated.
- `event_057` `character_fact_awareness.updated`: Private character fact awareness updated.
- `event_058` `character_fact_awareness.updated`: Private character fact awareness updated.
- `event_059` `character_fact_awareness.updated`: Private character fact awareness updated.
- `event_060` `memory_candidate.created`: Memory candidate `memory.player.accused.dockmaster.dockmaster_opened_warehouse` created.
- `event_061` `agent_memory_snapshot.updated`: Memory snapshot `memory.player.accused.dockmaster.dockmaster_opened_warehouse` create from `event_060`.
- `event_062` `character_impression.updated`: Private character impression updated.
- `event_063` `memory_candidate.created`: Memory candidate `memory.player.accusation_evaluated.dockmaster.dockmaster_opened_warehouse.correct` created.
- `event_064` `agent_memory_snapshot.updated`: Memory snapshot `memory.player.accusation_evaluated.dockmaster.dockmaster_opened_warehouse.correct` create from `event_063`.
- `event_065` `narrative.beat.completed`: Narrative beat `case_solved` completed.
- `event_066` `narrative.phase.changed`: Narrative phase changed from `expose` to `resolved`.
- `event_067` `rule.rejected`: Rejected `narrative.phase.change`: narrative phase changes must be driven by narrative rules.

## Discovered clues

- inward_tide_mark
- inward_broken_lamp
- blue_ledger_page

## Player knowledge

- `player_knowledge.warehouse_opened_after_tide` from clue `inward_tide_mark`: 仓库门在涨潮后被打开 - 向内延伸的潮痕说明仓库门曾在涨潮后被打开。
- `player_knowledge.lamp_broken_from_inside_entry` from clue `inward_broken_lamp`: 煤油灯因入门碰撞破裂 - 破裂方向说明煤油灯是在有人进门后被撞倒。
- `player_knowledge.blue_ledger_records_midnight_boxes` from clue `blue_ledger_page`: 蓝墨账页记录午夜木箱 - 蓝墨账页记录了午夜后入库的三只木箱。

## Relationship changes

- `dockmaster->player` deltas {'suspicion': 1.0, 'hostility': 1.0}; current {'source_id': 'dockmaster', 'target_id': 'player', 'trust': 0.0, 'suspicion': 1.0, 'fear': 0.0, 'intimacy': 0.0, 'hostility': 1.0}
- `dockmaster->player` crossed `suspicion` as `guarded`
- `dockmaster->player` deltas {'suspicion': 1.0, 'hostility': 1.0}; current {'source_id': 'dockmaster', 'target_id': 'player', 'trust': 0.0, 'suspicion': 1.0, 'fear': 0.0, 'intimacy': 0.0, 'hostility': 1.0}
- `clerk->player` deltas {'fear': 1.0}; current {'source_id': 'clerk', 'target_id': 'player', 'trust': -1.0, 'suspicion': 0.0, 'fear': 1.0, 'intimacy': 0.0, 'hostility': 0.0}
- `clerk->player` crossed `fear` as `afraid`
- `dockmaster->player` deltas {'suspicion': 1.0}; current {'source_id': 'dockmaster', 'target_id': 'player', 'trust': 0.0, 'suspicion': 1.0, 'fear': 0.0, 'intimacy': 0.0, 'hostility': 1.0}

## Memory snapshots

- `memory.player.clue_discovered.inward_tide_mark` create; salience `0.8`; sources `event_003`; Player discovered clue '向内延伸的潮痕'.
- `memory.player.asked_about.dockmaster.clue.inward_tide_mark` create; salience `0.6`; sources `event_009`; Player asked 赵码头长 about clue 'inward_tide_mark' with pressure 0.6.
- `memory.player.relationship_threshold.dockmaster.player.suspicion.guarded` create; salience `0.7`; sources `event_012`; 赵码头长 became guarded toward the player (suspicion).
- `memory.player.director_blocked.clerk.redacted_fact` create; salience `0.9`; sources `event_024`; Conversation with 沈账房 was blocked by narrative rules.
- `memory.player.clue_discovered.inward_broken_lamp` create; salience `0.8`; sources `event_029`; Player discovered clue '向内破裂的煤油灯'.
- `memory.player.clue_discovered.blue_ledger_page` create; salience `0.8`; sources `event_034`; Player discovered clue '蓝墨账页'.
- `memory.player.presented_clue.clerk.blue_ledger_page` create; salience `0.9`; sources `event_040`; Player pressured 沈账房 with clue 'blue_ledger_page' at pressure 0.9.
- `memory.player.relationship_threshold.clerk.player.fear.afraid` create; salience `0.7`; sources `event_043`; 沈账房 became afraid toward the player (fear).
- `memory.player.accused.dockmaster.dockmaster_opened_warehouse` create; salience `1.0`; sources `event_054`; Player formally accused 赵码头长 with claim 'dockmaster_opened_warehouse' using evidence ['inward_tide_mark', 'inward_broken_lamp', 'blue_ledger_page'].
- `memory.player.accusation_evaluated.dockmaster.dockmaster_opened_warehouse.correct` create; salience `1.0`; sources `event_055`; Rule Engine evaluated the accusation against 赵码头长 for claim 'dockmaster_opened_warehouse' as correct.

## Accusation result

- Target `dockmaster`, claim `dockmaster_opened_warehouse`, result `correct`, matched evidence `blue_ledger_page, inward_broken_lamp, inward_tide_mark`, missing evidence ``

## Final runtime state summary

- Narrative phase: `resolved`
- Completed beats: `tide_trace_found, ledger_pattern_found, case_solved`
- Discovered clues: `inward_tide_mark, inward_broken_lamp, blue_ledger_page`
- Player knowledge: `player_knowledge.warehouse_opened_after_tide, player_knowledge.lamp_broken_from_inside_entry, player_knowledge.blue_ledger_records_midnight_boxes`
- Memory snapshots: `memory.player.clue_discovered.inward_tide_mark, memory.player.asked_about.dockmaster.clue.inward_tide_mark, memory.player.relationship_threshold.dockmaster.player.suspicion.guarded, memory.player.director_blocked.clerk.redacted_fact, memory.player.clue_discovered.inward_broken_lamp, memory.player.clue_discovered.blue_ledger_page, memory.player.presented_clue.clerk.blue_ledger_page, memory.player.relationship_threshold.clerk.player.fear.afraid, memory.player.accused.dockmaster.dockmaster_opened_warehouse, memory.player.accusation_evaluated.dockmaster.dockmaster_opened_warehouse.correct`
- Relationship records: `6`
- Event count: `67`
