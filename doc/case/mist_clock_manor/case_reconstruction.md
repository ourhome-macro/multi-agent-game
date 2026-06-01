# 《雾钟山庄》标准运行复盘

> 本文档由 `scripts/generate_case_run.py` 执行 `mist_clock_manor` 标准路径后生成。
> 对应机器可读日志见 `standard_run.json`。

## 案件概览

暴雨夜，剧作家陆澜生死于雾钟山庄书房。表面上，这是一个反锁密室死亡；实际上，死亡由多名在场者的行为共同推向终点。

酒中的镇静剂、被替换的录音带、被改造的延迟门锁、被调换为空胶囊的心脏药，以及死亡前后的断电，共同构成了死亡链。

这个案件的关键不是寻找单一凶手，而是重建“谁在什么时间推动了哪一环”。

运行时通过 `WorldInfo` 锚定每个事实，通过线索逐步释放事实，再由 `NarrativeDirector` 阻止阶段外剧透。

## 标准调查路径

1. 检查酒桌：accepted=true，phase=`investigation`。事件：`player.inspected`, `clue.discovered`, `player_knowledge.updated`, `memory_candidate.created`, `agent_memory_snapshot.updated`, `narrative.beat.completed`, `narrative.phase.changed`。玩家已知：`sedative_wine`。
2. 询问林栖迟酒液问题：accepted=true，phase=`investigation`。事件：`player.asked_about`, `npc.replied`, `relationship.changed`, `relationship.threshold.crossed`, `character_impression.updated`, `character_fact_awareness.updated`, `memory_candidate.created`, `agent_memory_snapshot.updated`, `character_impression.updated`, `memory_candidate.created`, `agent_memory_snapshot.updated`。玩家已知：`sedative_wine`。
3. 向林栖迟展示酒液线索：accepted=true，phase=`investigation`。事件：`player.presented_clue`, `npc.replied`, `relationship.changed`, `character_impression.updated`, `character_fact_awareness.updated`, `memory_candidate.created`, `agent_memory_snapshot.updated`。玩家已知：`sedative_wine`。
4. 检查书房门锁：accepted=true，phase=`investigation`。事件：`player.inspected`, `clue.discovered`, `player_knowledge.updated`, `memory_candidate.created`, `agent_memory_snapshot.updated`。玩家已知：`sedative_wine`, `timed_lock_modified`。
5. 检查录音机：accepted=true，phase=`confrontation`。事件：`player.inspected`, `clue.discovered`, `clue.discovered`, `player_knowledge.updated`, `memory_candidate.created`, `agent_memory_snapshot.updated`, `player_knowledge.updated`, `memory_candidate.created`, `agent_memory_snapshot.updated`, `narrative.beat.completed`, `narrative.phase.changed`。玩家已知：`jiang_ruolan_recording_exists`, `recording_tape_swapped`, `sedative_wine`, `timed_lock_modified`。
6. 试探江雁回禁说事实：accepted=false，phase=`confrontation`；Director 拦截。事件：`player.talked`, `director.blocked`, `character_impression.updated`, `memory_candidate.created`, `agent_memory_snapshot.updated`。玩家已知：`jiang_ruolan_recording_exists`, `recording_tape_swapped`, `sedative_wine`, `timed_lock_modified`。
7. 向江雁回展示门锁线索：accepted=true，phase=`confrontation`。事件：`player.presented_clue`, `npc.replied`, `relationship.changed`, `relationship.threshold.crossed`, `character_impression.updated`, `character_fact_awareness.updated`, `memory_candidate.created`, `agent_memory_snapshot.updated`, `character_impression.updated`, `memory_candidate.created`, `agent_memory_snapshot.updated`。玩家已知：`jiang_ruolan_recording_exists`, `recording_tape_swapped`, `sedative_wine`, `timed_lock_modified`。
8. 检查烧毁供词：accepted=true，phase=`confrontation`。事件：`player.inspected`, `clue.discovered`, `player_knowledge.updated`, `memory_candidate.created`, `agent_memory_snapshot.updated`。玩家已知：`fake_confession_plan`, `jiang_ruolan_recording_exists`, `recording_tape_swapped`, `sedative_wine`, `timed_lock_modified`。
9. 检查药盒：accepted=true，phase=`confrontation`。事件：`player.inspected`, `clue.discovered`, `player_knowledge.updated`, `memory_candidate.created`, `agent_memory_snapshot.updated`。玩家已知：`fake_confession_plan`, `heart_medicine_replaced`, `jiang_ruolan_recording_exists`, `recording_tape_swapped`, `sedative_wine`, `timed_lock_modified`。
10. 检查电闸箱：accepted=true，phase=`reconstruction`。事件：`player.inspected`, `clue.discovered`, `player_knowledge.updated`, `memory_candidate.created`, `agent_memory_snapshot.updated`, `narrative.beat.completed`, `narrative.phase.changed`。玩家已知：`fake_confession_plan`, `heart_medicine_replaced`, `jiang_ruolan_recording_exists`, `power_cut_by_shen`, `recording_tape_swapped`, `sedative_wine`, `timed_lock_modified`。
11. 正式指控共同死亡链：accepted=true，phase=`resolved`。事件：`player.accused`, `accusation.evaluated`, `character_impression.updated`, `character_fact_awareness.updated`, `character_fact_awareness.updated`, `character_fact_awareness.updated`, `character_fact_awareness.updated`, `character_fact_awareness.updated`, `character_fact_awareness.updated`, `memory_candidate.created`, `agent_memory_snapshot.updated`, `character_impression.updated`, `memory_candidate.created`, `agent_memory_snapshot.updated`, `narrative.beat.completed`, `narrative.phase.changed`。玩家已知：`fake_confession_plan`, `heart_medicine_replaced`, `jiang_ruolan_recording_exists`, `power_cut_by_shen`, `recording_tape_swapped`, `sedative_wine`, `timed_lock_modified`。

## 案件事实重建

1. 陆澜生计划利用录音、供词和基金会安排清洗旧案，把江若岚之死重新包装为对自己有利的叙事。
2. 林栖迟在酒中加入镇静剂，原意不是直接杀人，但陆澜生饮下后，身体和判断能力被削弱。
3. 祁宴曾调换录音带，使陆澜生在书房听到足以撕开旧案的声音刺激。
4. 江雁回改造书房门锁，让密室反锁效果出现延迟，并将陆澜生的心脏药替换成空胶囊。
5. 沈照夜切断电源，使关键时间段的求救、判断和现场反应被进一步打乱。
6. 陆澜生最终死于心脏病、药物失效、精神刺激和现场延误共同叠加后的结果。
7. 因此，本案的正确指控不是“某一个人独立杀人”，而是“多人的动机和行动共同形成死亡链”。

## 玩家最终已知

- `fake_confession_plan`：陆澜生准备伪造忏悔信洗白旧案；来源线索 `burned_confession`（烧毁半截的忏悔信附录），source_type=`clue`，acquisition=`discovered`，置信度 1。
- `heart_medicine_replaced`：陆澜生的心脏病药被换成空胶囊；来源线索 `empty_capsules`（重量异常的心脏病胶囊），source_type=`clue`，acquisition=`discovered`，置信度 1。
- `jiang_ruolan_recording_exists`：江若岚旧录音存在；来源线索 `ruolan_voice_tape`（江若岚的录音片段），source_type=`clue`，acquisition=`discovered`，置信度 1。
- `power_cut_by_shen`：沈照夜切断主电源；来源线索 `cut_power_trace`（被人为拉下的主电闸），source_type=`clue`，acquisition=`discovered`，置信度 1。
- `recording_tape_swapped`：书房录音带被替换；来源线索 `echo_tape`（标着“回声钟终稿”的磁带），source_type=`clue`，acquisition=`discovered`，置信度 1。
- `sedative_wine`：红酒中含有镇静剂；来源线索 `bitter_wine`（带苦味的红酒残液），source_type=`clue`，acquisition=`discovered`，置信度 1。
- `timed_lock_modified`：书房门锁被改成延时落锁；来源线索 `delayed_lock_marks`（门锁内侧的新划痕），source_type=`clue`，acquisition=`discovered`，置信度 1。

## 角色认知变化

- 江雁回 / `jiang_yanhui` 认知 `death_chain_shared`：四人的小动作共同促成死亡，stance=`conceals`，source_type=`character_card`，置信度 1。
- 江雁回 / `jiang_yanhui` 认知 `fake_confession_plan`：陆澜生准备伪造忏悔信洗白旧案，stance=`knows`，source_type=`player_accused`，置信度 1。
- 江雁回 / `jiang_yanhui` 认知 `heart_medicine_replaced`：陆澜生的心脏病药被换成空胶囊，stance=`conceals`，source_type=`player_accused`，置信度 1。
- 江雁回 / `jiang_yanhui` 认知 `jiang_ruolan_death_coverup`：江若岚十年前死亡被陆澜生掩盖，stance=`conceals`，source_type=`character_card`，置信度 1。
- 江雁回 / `jiang_yanhui` 认知 `jiang_ruolan_recording_exists`：江若岚旧录音存在，stance=`conceals`，source_type=`character_card`，置信度 1。
- 江雁回 / `jiang_yanhui` 认知 `power_cut_by_shen`：沈照夜切断主电源，stance=`knows`，source_type=`player_accused`，置信度 0.95。
- 江雁回 / `jiang_yanhui` 认知 `recording_tape_swapped`：书房录音带被替换，stance=`conceals`，source_type=`player_accused`，置信度 1。
- 江雁回 / `jiang_yanhui` 认知 `sedative_wine`：红酒中含有镇静剂，stance=`knows`，source_type=`player_accused`，置信度 0.95。
- 江雁回 / `jiang_yanhui` 认知 `timed_lock_modified`：书房门锁被改成延时落锁，stance=`conceals`，source_type=`player_accused`，置信度 1。
- 林栖迟 / `lin_qichi` 认知 `fake_confession_plan`：陆澜生准备伪造忏悔信洗白旧案，stance=`knows`，source_type=`character_card`，置信度 1。
- 林栖迟 / `lin_qichi` 认知 `sedative_wine`：红酒中含有镇静剂，stance=`conceals`，source_type=`player_presented_clue`，置信度 1。
- 祁宴 / `qi_yan` 认知 `fake_confession_plan`：陆澜生准备伪造忏悔信洗白旧案，stance=`knows`，source_type=`character_card`，置信度 1。
- 祁宴 / `qi_yan` 认知 `jiang_ruolan_recording_exists`：江若岚旧录音存在，stance=`conceals`，source_type=`character_card`，置信度 1。
- 祁宴 / `qi_yan` 认知 `recording_tape_swapped`：书房录音带被替换，stance=`conceals`，source_type=`character_card`，置信度 1。
- 沈照夜 / `shen_zhaoye` 认知 `death_chain_shared`：四人的小动作共同促成死亡，stance=`conceals`，source_type=`character_card`，置信度 1。
- 沈照夜 / `shen_zhaoye` 认知 `jiang_ruolan_death_coverup`：江若岚十年前死亡被陆澜生掩盖，stance=`conceals`，source_type=`character_card`，置信度 1。
- 沈照夜 / `shen_zhaoye` 认知 `power_cut_by_shen`：沈照夜切断主电源，stance=`conceals`，source_type=`character_card`，置信度 1。

## Director 拦截结果

标准路径第 6 步在 `confrontation` 阶段强制触发江雁回相关禁说事实探针。运行时应返回 `director.blocked`，拒绝原始越界台词，并使用安全降级台词。

- 第 6 步 `试探江雁回禁说事实` 触发 `director.blocked`：target=`jiang_yanhui`，blocked_fact=`jiang_yanhui_mechanism`，world_info=`heart_medicine_replaced`，matched_text=`[redacted]`。

## Replay 校验

- `event_count`：91
- `replayed_event_count`：91
- `state_summary_equal`：true
- `player_knowledge_equal`：true
- `character_fact_awareness_equal`：true
- `character_impressions_equal`：true
- `memory_candidates_equal`：true
- `memory_snapshots_equal`：true
- `all_equal`：true

## 最终状态

- 最终 phase：`resolved`
- 完成 beats：`case_solved`, `mechanism_exposed`, `motive_chain_exposed`, `sedative_found`
- 已发现线索：`bitter_wine`, `burned_confession`, `cut_power_trace`, `delayed_lock_marks`, `echo_tape`, `empty_capsules`, `ruolan_voice_tape`
- 事件总数：91

## 产物说明

- `standard_run.json`：标准路径动作、每步新增事件、最终状态、完整事件日志和 replay 校验结果。
- 本文档：面向案件作者和系统评测的复盘文档，不作为玩家端直接展示文本。
