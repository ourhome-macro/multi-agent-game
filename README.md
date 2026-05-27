# LLM 多智能体悬疑叙事游戏后端运行时骨架

这是一个案件无关的后端叙事运行时框架。当前阶段使用内存存储、fake case、mock Agent 跑通最小闭环，不接真实 LLM、不接数据库、不做向量记忆。

## 运行

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload
```

服务启动时会自动加载 `cases/fake_case`。如果 YAML 配置存在引用错误，启动会失败并抛出明确错误。

## 测试

```powershell
py -3.12 -m pytest
py -3.12 -m ruff check .
```

## 最小链路

```text
Case Package
  -> Create Session
  -> PlayerAction
  -> Load SessionState / WorldState
  -> Mock Agent generates AgentIntent
  -> Narrative Director validates narrative boundary
  -> Rule Engine applies legal state changes
  -> Write WorldEvent
  -> Return State Summary
```

## 核心接口

- `GET /health`
- `GET /cases`
- `POST /sessions`
- `GET /sessions/{session_id}/state`
- `POST /sessions/{session_id}/actions`
- `GET /sessions/{session_id}/events`
