# P0 Regression Matrix

`app/evaluations/p0_regression_matrix.py` provides a deterministic regression matrix for P0 narrative safety paths. It does not call a real LLM. Each case declares the narrative phase, player input, and expected outcomes for one or more dimensions:

- `memory`: required and forbidden `memory_id` recall.
- `director`: allowed or blocked `world_info_id` / claim exposure.
- `action_intake`: accepted, ambiguous, or rejected structured action intake.
- `deduction`: accepted or rejected deduction result, including reject code and missing evidence/world info.

The matrix compares declared expectations against an injected `actual_provider`. This keeps the evaluation layer independent from Action Intake, Director, Memory, and Deduction implementations while still allowing tests to adapt deterministic outputs from those components.

Failure reports include `case_id`, `phase`, raw matrix `input_text`, failed dimension, expected payload, and actual payload. This is intentional CI output: a P0 regression must identify the exact case and boundary that drifted.

Run:

```powershell
pytest tests/test_p0_regression_matrix.py
```
