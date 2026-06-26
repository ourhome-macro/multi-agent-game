# P2 Large File Refactor - 2026-06-26

## Scope

本轮处理 P2 的大文件维护风险，重点拆 `app/runtime/derivations.py` 与 `app/agents/real_llm_agent.py`。目标是降低入口文件职责密度，不改变事件语义、LLM 输出合同或 NPC 可见性边界。

## Runtime Derivation Split

`DerivedEventSystem` 保留为运行时派生入口，只负责按 `WorldEvent.type` 编排派生流程。

拆出的模块边界如下：

- `app/runtime/derivation_impressions.py`：NPC 对玩家的私有画像更新。
- `app/runtime/derivation_clue_memory.py`：线索发现、重构链路 belief / strategy 记忆。
- `app/runtime/derivation_scene_shared_memory.py`：公开展示线索产生的 scene-shared 记忆和在场 NPC 私有解释。
- `app/runtime/derivation_accusation_memory.py`：玩家正式指控与指控结果记忆。
- `app/runtime/derivation_interaction_memory.py`：询问、展示证据、关系阈值、Director block、配置化 memory rule。
- `app/runtime/derivation_memory_store.py`：memory candidate 幂等落库和事件 payload 统一生成。
- `app/runtime/derivation_memory_constants.py`：内置 Python fallback 规则 ID。
- `app/runtime/derivation_utils.py`：无状态列表、topic tag、clamp helper。

拆分后 `app/runtime/derivations.py` 从约 1425 行降到 332 行，主文件不再承载 memory rule 仓库。

## LLM Provider Split

`OpenAILLMAgent` 保留 provider client、HTTP retry、Responses / Chat Completions fallback 和安全拒答入口。

已拆出的模块边界如下：

- `app/agents/provider_payload.py`：compact provider DTO，避免把完整 `LLMAgentContractInput` 直接喂给真实模型。
- `app/agents/provider_schema.py`：动态 JSON schema。
- `app/agents/provider_repair.py`：本地合同投影、schema/json error summary、repair helper、disclosure matrix。

`app/agents/real_llm_agent.py` 从约 1524 行降到约 798 行。它仍然偏大，但剩余职责集中在 provider transport 和错误处理，后续可再拆 `provider_errors.py` 与 `provider_config.py`。

## Behavior Fix Found During Refactor

`MemoryArchivalSystem` 原先使用最新事件时间作为归档时钟。第一次归档会追加一个当前时间的 `agent_memory_snapshot.updated(operation=archive)`，第二次归档又把这个系统审计事件当作业务时钟，导致 recent working memory 被误归档。

修复后：

- 如果传入 `caused_by_event_id`，归档时钟锚定到该业务事件。
- fallback 时跳过 `memory_archival_system` 自己产生的 archive 事件。
- 归档审计事件仍保留当前写入时间，但不会反向推进下一轮归档判断。

## Redundancy Notes

已发现但本轮不强行改动的精简点：

- memory id 仍以多处 f-string 拼装。后续可引入每类事件的稳定 id builder，但必须补充回放和去重测试，避免改坏现有幂等键。
- `privacy_reason`、`topic_tags`、`source_memory_ids` 的 metadata 组装仍有重复形态。后续适合在各业务模块内收敛为小型 helper，而不是做跨模块万能 builder。
- `OpenAILLMAgent` 仍混有错误分类、env config、JSON response parsing。它们可拆成 `provider_errors.py`、`provider_config.py`、`provider_response.py`，但当前不是 LLM token 浪费的根因。
- `derivation_interaction_memory.py` 同时包含配置化 rule 和 Python fallback。后续当更多 fallback 迁到 YAML rule 后，这个文件应继续缩小。

## Verification

- `py -3.12 -m ruff check ...`：通过。
- 聚焦回归 60 个测试通过，覆盖 memory archival、memory v2、NPC skill events、present clue contract、character impression、LLM provider payload、real LLM observability、agent turn plan skill contract、real LLM schema tests。

