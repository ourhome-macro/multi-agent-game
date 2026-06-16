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
- `event_004` `player_knowledge.updated`: Player knowledge `player_knowledge.warehouse_opened_after_tide` updated.
- `event_005` `memory_candidate.created`: Memory candidate `memory.player.clue_discovered.inward_tide_mark` created.
- `event_006` `agent_memory_snapshot.updated`: Memory snapshot `memory.player.clue_discovered.inward_tide_mark` create from `event_005`.
- `event_007` `narrative.beat.completed`: Narrative beat `tide_trace_found` completed.
- `event_008` `narrative.phase.changed`: Narrative phase changed from `opening` to `pressure`.
- `event_009` `player.asked_about`: Player asked `dockmaster` about `clue:inward_tide_mark`.
- `event_010` `npc.replied`: NPC replied: "潮痕只能说明门开过，不能说明是谁开的。"
- `event_011` `character_impression.updated`: Private character impression updated.
- `event_012` `character_fact_awareness.updated`: Private character fact awareness updated.
- `event_013` `memory_candidate.created`: Memory candidate `memory.player.asked_about.dockmaster.clue.inward_tide_mark` created.
- `event_014` `agent_memory_snapshot.updated`: Memory snapshot `memory.player.asked_about.dockmaster.clue.inward_tide_mark` create from `event_013`.
- `event_015` `player.talked`: Player talked to `dockmaster`.
- `event_016` `npc.replied`: NPC replied: "潮痕只能说明门开过，不能说明是谁开的。"
- `event_017` `player.talked`: Player talked to `clerk`.
- `event_018` `director.blocked`: Director blocked an unsafe reply.
- `event_019` `character_impression.updated`: Private character impression updated.
- `event_020` `memory_candidate.created`: Memory candidate `memory.player.director_blocked.clerk.redacted_fact` created.
- `event_021` `agent_memory_snapshot.updated`: Memory snapshot `memory.player.director_blocked.clerk.redacted_fact` create from `event_020`.
- `event_022` `player.inspected`: Player inspected `broken_lamp`.
- `event_023` `clue.discovered`: Clue `inward_broken_lamp` discovered.
- `event_024` `player_knowledge.updated`: Player knowledge `player_knowledge.lamp_broken_from_inside_entry` updated.
- `event_025` `memory_candidate.created`: Memory candidate `memory.player.clue_discovered.inward_broken_lamp` created.
- `event_026` `agent_memory_snapshot.updated`: Memory snapshot `memory.player.clue_discovered.inward_broken_lamp` create from `event_025`.
- `event_027` `player.inspected`: Player inspected `ledger_box`.
- `event_028` `clue.discovered`: Clue `blue_ledger_page` discovered.
- `event_029` `player_knowledge.updated`: Player knowledge `player_knowledge.blue_ledger_records_midnight_boxes` updated.
- `event_030` `memory_candidate.created`: Memory candidate `memory.player.clue_discovered.blue_ledger_page` created.
- `event_031` `agent_memory_snapshot.updated`: Memory snapshot `memory.player.clue_discovered.blue_ledger_page` create from `event_030`.
- `event_032` `narrative.beat.completed`: Narrative beat `ledger_pattern_found` completed.
- `event_033` `narrative.phase.changed`: Narrative phase changed from `pressure` to `expose`.
- `event_034` `player.presented_clue`: Player presented clue `blue_ledger_page` to `clerk`.
- `event_035` `npc.replied`: NPC replied: "我只记录货物，不知道谁让箱子午夜后进仓。"
- `event_036` `character_impression.updated`: Private character impression updated.
- `event_037` `character_fact_awareness.updated`: Private character fact awareness updated.
- `event_038` `memory_candidate.created`: Memory candidate `memory.player.presented_clue.clerk.blue_ledger_page` created.
- `event_039` `agent_memory_snapshot.updated`: Memory snapshot `memory.player.presented_clue.clerk.blue_ledger_page` create from `event_038`.
- `event_040` `player.talked`: Player talked to `dockmaster`.
- `event_041` `npc.replied`: NPC replied: "那盏灯不是风吹的。有人进门太急，撞到了门后的箱子。"
- `event_042` `player.accused`: Player accused `dockmaster` with claim `dockmaster_opened_warehouse`.
- `event_043` `accusation.evaluated`: Accusation `dockmaster_opened_warehouse` evaluated as `correct`.
- `event_044` `character_impression.updated`: Private character impression updated.
- `event_045` `character_fact_awareness.updated`: Private character fact awareness updated.
- `event_046` `character_fact_awareness.updated`: Private character fact awareness updated.
- `event_047` `character_fact_awareness.updated`: Private character fact awareness updated.
- `event_048` `memory_candidate.created`: Memory candidate `memory.player.accused.dockmaster.dockmaster_opened_warehouse` created.
- `event_049` `agent_memory_snapshot.updated`: Memory snapshot `memory.player.accused.dockmaster.dockmaster_opened_warehouse` create from `event_048`.
- `event_050` `character_impression.updated`: Private character impression updated.
- `event_051` `memory_candidate.created`: Memory candidate `memory.player.accusation_evaluated.dockmaster.dockmaster_opened_warehouse.correct` created.
- `event_052` `agent_memory_snapshot.updated`: Memory snapshot `memory.player.accusation_evaluated.dockmaster.dockmaster_opened_warehouse.correct` create from `event_051`.
- `event_053` `narrative.beat.completed`: Narrative beat `case_solved` completed.
- `event_054` `narrative.phase.changed`: Narrative phase changed from `expose` to `resolved`.
- `event_055` `rule.rejected`: Rejected `narrative.phase.change`: narrative phase changes must be driven by narrative rules.

## Discovered clues

- inward_tide_mark
- inward_broken_lamp
- blue_ledger_page

## Player knowledge

- `player_knowledge.warehouse_opened_after_tide` from clue `inward_tide_mark`: 仓库门在涨潮后被打开 - 向内延伸的潮痕说明仓库门曾在涨潮后被打开。
- `player_knowledge.lamp_broken_from_inside_entry` from clue `inward_broken_lamp`: 煤油灯因入门碰撞破裂 - 破裂方向说明煤油灯是在有人进门后被撞倒。
- `player_knowledge.blue_ledger_records_midnight_boxes` from clue `blue_ledger_page`: 蓝墨账页记录午夜木箱 - 蓝墨账页记录了午夜后入库的三只木箱。

## Relationship changes

- None

## Memory snapshots

- `memory.player.clue_discovered.inward_tide_mark` create; salience `0.8`; sources `event_003`; Player discovered clue '向内延伸的潮痕'.
- `memory.player.asked_about.dockmaster.clue.inward_tide_mark` create; salience `0.6`; sources `event_009`; Player asked 赵码头长 about clue 'inward_tide_mark' with pressure 0.6.
- `memory.player.director_blocked.clerk.redacted_fact` create; salience `0.9`; sources `event_018`; Conversation with 沈账房 was blocked by narrative rules.
- `memory.player.clue_discovered.inward_broken_lamp` create; salience `0.8`; sources `event_023`; Player discovered clue '向内破裂的煤油灯'.
- `memory.player.clue_discovered.blue_ledger_page` create; salience `0.8`; sources `event_028`; Player discovered clue '蓝墨账页'.
- `memory.player.presented_clue.clerk.blue_ledger_page` create; salience `0.9`; sources `event_034`; Player pressured 沈账房 with clue 'blue_ledger_page' at pressure 0.9.
- `memory.player.accused.dockmaster.dockmaster_opened_warehouse` create; salience `1.0`; sources `event_042`; Player formally accused 赵码头长 with claim 'dockmaster_opened_warehouse' using evidence ['inward_tide_mark', 'inward_broken_lamp', 'blue_ledger_page'].
- `memory.player.accusation_evaluated.dockmaster.dockmaster_opened_warehouse.correct` create; salience `1.0`; sources `event_043`; Rule Engine evaluated the accusation against 赵码头长 for claim 'dockmaster_opened_warehouse' as correct.

## Accusation result

- Target `dockmaster`, claim `dockmaster_opened_warehouse`, result `correct`, matched evidence `blue_ledger_page, inward_broken_lamp, inward_tide_mark`, missing evidence ``

## Final runtime state summary

- Narrative phase: `resolved`
- Completed beats: `tide_trace_found, ledger_pattern_found, case_solved`
- Discovered clues: `inward_tide_mark, inward_broken_lamp, blue_ledger_page`
- Player knowledge: `player_knowledge.warehouse_opened_after_tide, player_knowledge.lamp_broken_from_inside_entry, player_knowledge.blue_ledger_records_midnight_boxes`
- Memory snapshots: `memory.player.clue_discovered.inward_tide_mark, memory.player.asked_about.dockmaster.clue.inward_tide_mark, memory.player.director_blocked.clerk.redacted_fact, memory.player.clue_discovered.inward_broken_lamp, memory.player.clue_discovered.blue_ledger_page, memory.player.presented_clue.clerk.blue_ledger_page, memory.player.accused.dockmaster.dockmaster_opened_warehouse, memory.player.accusation_evaluated.dockmaster.dockmaster_opened_warehouse.correct`
- Relationship records: `0`
- Event count: `55`
