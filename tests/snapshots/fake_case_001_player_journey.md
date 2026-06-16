# fake_case_001 Player Journey

## Case summary

- Case ID: `fake_case_001`
- Session ID: `session`
- Initial phase: `opening`
- Final phase: `resolved`
- Event count: `62`

## Timeline

- `event_001` `session.created`: Session created for `fake_case_001` in phase `opening`.
- `event_002` `player.inspected`: Player inspected `desk`.
- `event_003` `clue.discovered`: Clue `scratched_drawer` discovered.
- `event_004` `player_knowledge.updated`: Player knowledge `player_knowledge.desk_forced_open` updated.
- `event_005` `memory_candidate.created`: Memory candidate `memory.player.clue_discovered.scratched_drawer` created.
- `event_006` `agent_memory_snapshot.updated`: Memory snapshot `memory.player.clue_discovered.scratched_drawer` create from `event_005`.
- `event_007` `narrative.beat.completed`: Narrative beat `drawer_found` completed.
- `event_008` `narrative.phase.changed`: Narrative phase changed from `opening` to `investigation`.
- `event_009` `player.asked_about`: Player asked `butler` about `clue:scratched_drawer`.
- `event_010` `npc_skill.selected`: NPC skill selected for `butler`: `butler_drawer_pressure_deflection`.
- `event_011` `npc.replied`: NPC replied: "You keep returning to that drawer. Are you asking whether I opened it, or whether I know who did?"
- `event_012` `relationship.changed`: Relationship `butler->player` changed.
- `event_013` `character_impression.updated`: Private character impression updated.
- `event_014` `character_fact_awareness.updated`: Private character fact awareness updated.
- `event_015` `memory_candidate.created`: Memory candidate `memory.player.asked_about.butler.clue.scratched_drawer` created.
- `event_016` `agent_memory_snapshot.updated`: Memory snapshot `memory.player.asked_about.butler.clue.scratched_drawer` create from `event_015`.
- `event_017` `player.presented_clue`: Player presented clue `scratched_drawer` to `butler`.
- `event_018` `npc_skill.selected`: NPC skill selected for `butler`: `butler_drawer_pressure_deflection`.
- `event_019` `npc.replied`: NPC replied: "Those scratch marks mean someone forced the drawer, but I did not see who held the tool."
- `event_020` `relationship.changed`: Relationship `butler->player` changed.
- `event_021` `character_impression.updated`: Private character impression updated.
- `event_022` `character_fact_awareness.updated`: Private character fact awareness updated.
- `event_023` `memory_candidate.created`: Memory candidate `memory.player.presented_clue.butler.scratched_drawer` created.
- `event_024` `agent_memory_snapshot.updated`: Memory snapshot `memory.player.presented_clue.butler.scratched_drawer` create from `event_023`.
- `event_025` `player.talked`: Player talked to `butler`.
- `event_026` `npc_skill.rejected`: NPC skill rejected for `butler`: `butler_drawer_pressure_deflection`.
- `event_027` `npc.replied`: NPC replied: "抽屉确实有响动，但我不能确定是谁动过它。"
- `event_028` `player.inspected`: Player inspected `portrait`.
- `event_029` `clue.discovered`: Clue `dustless_frame` discovered.
- `event_030` `player_knowledge.updated`: Player knowledge `player_knowledge.portrait_was_moved` updated.
- `event_031` `memory_candidate.created`: Memory candidate `memory.player.clue_discovered.dustless_frame` created.
- `event_032` `agent_memory_snapshot.updated`: Memory snapshot `memory.player.clue_discovered.dustless_frame` create from `event_031`.
- `event_033` `player.talked`: Player talked to `butler`.
- `event_034` `npc_skill.rejected`: NPC skill rejected for `butler`: `butler_drawer_pressure_deflection`.
- `event_035` `npc.replied`: NPC replied: "抽屉确实有响动，但我不能确定是谁动过它。"
- `event_036` `player.talked`: Player talked to `butler`.
- `event_037` `npc_skill.rejected`: NPC skill rejected for `butler`: `butler_drawer_pressure_deflection`.
- `event_038` `director.blocked`: Director blocked an unsafe reply.
- `event_039` `character_impression.updated`: Private character impression updated.
- `event_040` `memory_candidate.created`: Memory candidate `memory.player.director_blocked.butler.redacted_fact` created.
- `event_041` `agent_memory_snapshot.updated`: Memory snapshot `memory.player.director_blocked.butler.redacted_fact` create from `event_040`.
- `event_042` `player.inspected`: Player inspected `carpet`.
- `event_043` `clue.discovered`: Clue `torn_note` discovered.
- `event_044` `player_knowledge.updated`: Player knowledge `player_knowledge.secret_meeting_note_exists` updated.
- `event_045` `memory_candidate.created`: Memory candidate `memory.player.clue_discovered.torn_note` created.
- `event_046` `agent_memory_snapshot.updated`: Memory snapshot `memory.player.clue_discovered.torn_note` create from `event_045`.
- `event_047` `narrative.beat.completed`: Narrative beat `hidden_meeting_connected` completed.
- `event_048` `narrative.phase.changed`: Narrative phase changed from `investigation` to `reveal`.
- `event_049` `player.accused`: Player accused `butler` with claim `butler_moved_key`.
- `event_050` `accusation.evaluated`: Accusation `butler_moved_key` evaluated as `correct`.
- `event_051` `character_impression.updated`: Private character impression updated.
- `event_052` `character_fact_awareness.updated`: Private character fact awareness updated.
- `event_053` `character_fact_awareness.updated`: Private character fact awareness updated.
- `event_054` `character_fact_awareness.updated`: Private character fact awareness updated.
- `event_055` `memory_candidate.created`: Memory candidate `memory.player.accused.butler.butler_moved_key` created.
- `event_056` `agent_memory_snapshot.updated`: Memory snapshot `memory.player.accused.butler.butler_moved_key` create from `event_055`.
- `event_057` `character_impression.updated`: Private character impression updated.
- `event_058` `memory_candidate.created`: Memory candidate `memory.player.accusation_evaluated.butler.butler_moved_key.correct` created.
- `event_059` `agent_memory_snapshot.updated`: Memory snapshot `memory.player.accusation_evaluated.butler.butler_moved_key.correct` create from `event_058`.
- `event_060` `narrative.beat.completed`: Narrative beat `case_solved` completed.
- `event_061` `narrative.phase.changed`: Narrative phase changed from `reveal` to `resolved`.
- `event_062` `rule.rejected`: Rejected `narrative.phase.change`: narrative phase changes must be driven by narrative rules.

## Discovered clues

- scratched_drawer
- dustless_frame
- torn_note

## Player knowledge

- `player_knowledge.desk_forced_open` from clue `scratched_drawer`: 书桌抽屉被撬开 - 书桌抽屉锁孔旁的新鲜划痕表明，抽屉在案发前后被非正常打开过。
- `player_knowledge.portrait_was_moved` from clue `dustless_frame`: 肖像画近期被移动过 - 肖像画背后的无尘痕迹说明它最近被移动过，可能遮挡过隐藏物。
- `player_knowledge.secret_meeting_note_exists` from clue `torn_note`: 存在十点书房会面便签 - 被撕碎的便签显示，有人在今晚十点约定于书房见面。

## Relationship changes

- `butler->player` deltas {'suspicion': 0.2}; current {'source_id': 'butler', 'target_id': 'player', 'trust': 0.0, 'suspicion': 0.2, 'fear': 1.0, 'intimacy': 0.0, 'hostility': 0.0}
- `butler->player` deltas {'suspicion': 0.2, 'trust': 0.1}; current {'source_id': 'butler', 'target_id': 'player', 'trust': 0.1, 'suspicion': 0.4, 'fear': 1.0, 'intimacy': 0.0, 'hostility': 0.0}

## Memory snapshots

- `memory.player.clue_discovered.scratched_drawer` create; salience `0.8`; sources `event_003`; Player discovered clue '抽屉划痕'.
- `memory.player.asked_about.butler.clue.scratched_drawer` create; salience `0.6`; sources `event_009`; Player asked 韩管家 about clue 'scratched_drawer' with pressure 0.6.
- `memory.player.presented_clue.butler.scratched_drawer` create; salience `0.9`; sources `event_017`; Player pressured 韩管家 with clue 'scratched_drawer' at pressure 0.9.
- `memory.player.clue_discovered.dustless_frame` create; salience `0.8`; sources `event_029`; Player discovered clue '无尘画框印'.
- `memory.player.director_blocked.butler.redacted_fact` create; salience `0.9`; sources `event_038`; Conversation with 韩管家 was blocked by narrative rules.
- `memory.player.clue_discovered.torn_note` create; salience `0.8`; sources `event_043`; Player discovered clue '被撕碎的便签'.
- `memory.player.accused.butler.butler_moved_key` create; salience `1.0`; sources `event_049`; Player formally accused 韩管家 with claim 'butler_moved_key' using evidence ['scratched_drawer', 'dustless_frame', 'torn_note'].
- `memory.player.accusation_evaluated.butler.butler_moved_key.correct` create; salience `1.0`; sources `event_050`; Rule Engine evaluated the accusation against 韩管家 for claim 'butler_moved_key' as correct.

## Accusation result

- Target `butler`, claim `butler_moved_key`, result `correct`, matched evidence `dustless_frame, scratched_drawer, torn_note`, missing evidence ``

## Final runtime state summary

- Narrative phase: `resolved`
- Completed beats: `drawer_found, hidden_meeting_connected, case_solved`
- Discovered clues: `scratched_drawer, dustless_frame, torn_note`
- Player knowledge: `player_knowledge.desk_forced_open, player_knowledge.portrait_was_moved, player_knowledge.secret_meeting_note_exists`
- Memory snapshots: `memory.player.clue_discovered.scratched_drawer, memory.player.asked_about.butler.clue.scratched_drawer, memory.player.presented_clue.butler.scratched_drawer, memory.player.clue_discovered.dustless_frame, memory.player.director_blocked.butler.redacted_fact, memory.player.clue_discovered.torn_note, memory.player.accused.butler.butler_moved_key, memory.player.accusation_evaluated.butler.butler_moved_key.correct`
- Relationship records: `2`
- Event count: `62`
