# fake_case_001 Player Journey

## Case summary

- Case ID: `fake_case_001`
- Session ID: `session`
- Initial phase: `opening`
- Final phase: `resolved`
- Event count: `58`

## Timeline

- `event_001` `session.created`: Session created for `fake_case_001` in phase `opening`.
- `event_002` `player.inspected`: Player inspected `desk`.
- `event_003` `clue.discovered`: Clue `scratched_drawer` discovered.
- `event_004` `player_knowledge.updated`: Player knowledge `player_knowledge.scratched_drawer` updated.
- `event_005` `memory_candidate.created`: Memory candidate `memory.player.clue_discovered.scratched_drawer` created.
- `event_006` `agent_memory_snapshot.updated`: Memory snapshot `memory.player.clue_discovered.scratched_drawer` created from `event_005`.
- `event_007` `narrative.beat.completed`: Narrative beat `drawer_found` completed.
- `event_008` `narrative.phase.changed`: Narrative phase changed from `opening` to `investigation`.
- `event_009` `player.asked_about`: Player asked `butler` about `clue:scratched_drawer`.
- `event_010` `npc.replied`: NPC replied: "You keep returning to that drawer. Are you asking whether I opened it, or whether I know who did?"
- `event_011` `relationship.changed`: Relationship `butler->player` changed.
- `event_012` `character_impression.updated`: Private character impression updated.
- `event_013` `memory_candidate.created`: Memory candidate `memory.player.asked_about.butler.clue.scratched_drawer` created.
- `event_014` `agent_memory_snapshot.updated`: Memory snapshot `memory.player.asked_about.butler.clue.scratched_drawer` created from `event_013`.
- `event_015` `player.presented_clue`: Player presented clue `scratched_drawer` to `butler`.
- `event_016` `npc.replied`: NPC replied: "Those scratch marks mean someone forced the drawer, but I did not see who held the tool."
- `event_017` `relationship.changed`: Relationship `butler->player` changed.
- `event_018` `relationship.threshold.crossed`: Relationship threshold `suspicion` crossed as `guarded`.
- `event_019` `character_impression.updated`: Private character impression updated.
- `event_020` `memory_candidate.created`: Memory candidate `memory.player.presented_clue.butler.scratched_drawer` created.
- `event_021` `agent_memory_snapshot.updated`: Memory snapshot `memory.player.presented_clue.butler.scratched_drawer` created from `event_020`.
- `event_022` `character_impression.updated`: Private character impression updated.
- `event_023` `memory_candidate.created`: Memory candidate `memory.player.relationship_threshold.butler.player.suspicion.guarded` created.
- `event_024` `agent_memory_snapshot.updated`: Memory snapshot `memory.player.relationship_threshold.butler.player.suspicion.guarded` created from `event_023`.
- `event_025` `player.talked`: Player talked to `butler`.
- `event_026` `npc.replied`: NPC replied: "抽屉确实有响动，但我不能确定是谁动过它。"
- `event_027` `relationship.changed`: Relationship `butler->player` changed.
- `event_028` `player.inspected`: Player inspected `portrait`.
- `event_029` `clue.discovered`: Clue `dustless_frame` discovered.
- `event_030` `player_knowledge.updated`: Player knowledge `player_knowledge.dustless_frame` updated.
- `event_031` `memory_candidate.created`: Memory candidate `memory.player.clue_discovered.dustless_frame` created.
- `event_032` `agent_memory_snapshot.updated`: Memory snapshot `memory.player.clue_discovered.dustless_frame` created from `event_031`.
- `event_033` `player.talked`: Player talked to `butler`.
- `event_034` `npc.replied`: NPC replied: "抽屉确实有响动，但我不能确定是谁动过它。"
- `event_035` `relationship.changed`: Relationship `butler->player` changed.
- `event_036` `player.talked`: Player talked to `butler`.
- `event_037` `director.blocked`: Director blocked an unsafe reply.
- `event_038` `character_impression.updated`: Private character impression updated.
- `event_039` `memory_candidate.created`: Memory candidate `memory.player.director_blocked.butler.redacted_fact` created.
- `event_040` `agent_memory_snapshot.updated`: Memory snapshot `memory.player.director_blocked.butler.redacted_fact` created from `event_039`.
- `event_041` `player.inspected`: Player inspected `carpet`.
- `event_042` `clue.discovered`: Clue `torn_note` discovered.
- `event_043` `player_knowledge.updated`: Player knowledge `player_knowledge.torn_note` updated.
- `event_044` `memory_candidate.created`: Memory candidate `memory.player.clue_discovered.torn_note` created.
- `event_045` `agent_memory_snapshot.updated`: Memory snapshot `memory.player.clue_discovered.torn_note` created from `event_044`.
- `event_046` `narrative.beat.completed`: Narrative beat `hidden_meeting_connected` completed.
- `event_047` `narrative.phase.changed`: Narrative phase changed from `investigation` to `reveal`.
- `event_048` `player.accused`: Player accused `butler` with claim `butler_moved_key`.
- `event_049` `accusation.evaluated`: Accusation `butler_moved_key` evaluated as `correct`.
- `event_050` `character_impression.updated`: Private character impression updated.
- `event_051` `memory_candidate.created`: Memory candidate `memory.player.accused.butler.butler_moved_key` created.
- `event_052` `agent_memory_snapshot.updated`: Memory snapshot `memory.player.accused.butler.butler_moved_key` created from `event_051`.
- `event_053` `character_impression.updated`: Private character impression updated.
- `event_054` `memory_candidate.created`: Memory candidate `memory.player.accusation_evaluated.butler.butler_moved_key.correct` created.
- `event_055` `agent_memory_snapshot.updated`: Memory snapshot `memory.player.accusation_evaluated.butler.butler_moved_key.correct` created from `event_054`.
- `event_056` `narrative.beat.completed`: Narrative beat `case_solved` completed.
- `event_057` `narrative.phase.changed`: Narrative phase changed from `reveal` to `resolved`.
- `event_058` `rule.rejected`: Rejected `narrative.phase.change`: narrative phase changes must be driven by narrative rules.

## Discovered clues

- scratched_drawer
- dustless_frame
- torn_note

## Player knowledge

- `player_knowledge.scratched_drawer` from clue `scratched_drawer`: 抽屉划痕 - 书桌抽屉锁孔旁有新鲜划痕，像是被细金属工具撬开过。
- `player_knowledge.dustless_frame` from clue `dustless_frame`: 无尘画框印 - 肖像画背后的墙面有一圈无尘痕迹，说明它最近被移动过。
- `player_knowledge.torn_note` from clue `torn_note`: 被撕碎的便签 - 便签只剩半截，上面写着“今晚十点，书房见”。

## Relationship changes

- `butler->player` deltas {'suspicion': 0.4, 'fear': 0.2}; current {'source_id': 'butler', 'target_id': 'player', 'trust': 0.0, 'suspicion': 0.4, 'fear': 1.0, 'intimacy': 0.0, 'hostility': 0.0}
- `butler->player` deltas {'suspicion': 0.7, 'trust': 0.2}; current {'source_id': 'butler', 'target_id': 'player', 'trust': 0.2, 'suspicion': 1.0, 'fear': 1.0, 'intimacy': 0.0, 'hostility': 0.0}
- `butler->player` crossed `suspicion` as `guarded`
- `butler->player` deltas {'fear': 1.0, 'suspicion': 1.0}; current {'source_id': 'butler', 'target_id': 'player', 'trust': 0.2, 'suspicion': 1.0, 'fear': 1.0, 'intimacy': 0.0, 'hostility': 0.0}
- `butler->player` deltas {'fear': 1.0, 'suspicion': 1.0}; current {'source_id': 'butler', 'target_id': 'player', 'trust': 0.2, 'suspicion': 1.0, 'fear': 1.0, 'intimacy': 0.0, 'hostility': 0.0}

## Memory snapshots

- `memory.player.clue_discovered.scratched_drawer` created; salience `0.8`; sources `event_003`; Player discovered clue '抽屉划痕'.
- `memory.player.asked_about.butler.clue.scratched_drawer` created; salience `0.6`; sources `event_009`; Player asked 韩管家 about clue 'scratched_drawer' with pressure 0.6.
- `memory.player.presented_clue.butler.scratched_drawer` created; salience `0.9`; sources `event_015`; Player pressured 韩管家 with clue 'scratched_drawer' at pressure 0.9.
- `memory.player.relationship_threshold.butler.player.suspicion.guarded` created; salience `0.7`; sources `event_018`; 韩管家 became guarded toward the player (suspicion).
- `memory.player.clue_discovered.dustless_frame` created; salience `0.8`; sources `event_029`; Player discovered clue '无尘画框印'.
- `memory.player.director_blocked.butler.redacted_fact` created; salience `0.9`; sources `event_037`; Conversation with 韩管家 was blocked by narrative rules.
- `memory.player.clue_discovered.torn_note` created; salience `0.8`; sources `event_042`; Player discovered clue '被撕碎的便签'.
- `memory.player.accused.butler.butler_moved_key` created; salience `1.0`; sources `event_048`; Player formally accused 韩管家 with claim 'butler_moved_key' using evidence ['scratched_drawer', 'dustless_frame', 'torn_note'].
- `memory.player.accusation_evaluated.butler.butler_moved_key.correct` created; salience `1.0`; sources `event_049`; Rule Engine evaluated the accusation against 韩管家 for claim 'butler_moved_key' as correct.

## Accusation result

- Target `butler`, claim `butler_moved_key`, result `correct`, matched evidence `dustless_frame, scratched_drawer, torn_note`, missing evidence ``

## Final runtime state summary

- Narrative phase: `resolved`
- Completed beats: `drawer_found, hidden_meeting_connected, case_solved`
- Discovered clues: `scratched_drawer, dustless_frame, torn_note`
- Player knowledge: `player_knowledge.scratched_drawer, player_knowledge.dustless_frame, player_knowledge.torn_note`
- Memory snapshots: `memory.player.clue_discovered.scratched_drawer, memory.player.asked_about.butler.clue.scratched_drawer, memory.player.presented_clue.butler.scratched_drawer, memory.player.relationship_threshold.butler.player.suspicion.guarded, memory.player.clue_discovered.dustless_frame, memory.player.director_blocked.butler.redacted_fact, memory.player.clue_discovered.torn_note, memory.player.accused.butler.butler_moved_key, memory.player.accusation_evaluated.butler.butler_moved_key.correct`
- Relationship records: `5`
- Event count: `58`
