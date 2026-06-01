# LLM Shadow Eval Report: mist_clock_manor

- Scenario: `cases\mist_clock_manor\scenarios\standard_path.yaml`
- Backend: `real`
- Real shadow enabled: `true`
- State unchanged: `true`

## Summary

- total_shadow_calls: `4`
- schema_failure_count: `0`
- director_block_count: `0`
- missing_disclosure_claim_count: `0`
- speech_touched_world_info_count: `0`
- mode_violation_count: `0`
- full_reveal_block_count: `0`
- fallback_count: `0`
- skipped_count: `0`
- state_unchanged: `true`

## Steps

### Step 2: ask lin about wine updates only lin awareness

- Action: `ask_about` -> `lin_qichi`
- Phase: `investigation`
- LLM success: `true`
- Schema valid: `true`
- Director blocked: `false`
- Block reason: `none`
- Disclosure claims: `1`
- Speech touched WorldInfo: `false`
- Missing disclosure claim: `false`
- Fallback used: `false`
- State unchanged: `true`

### Step 3: present wine keeps player knowledge unchanged

- Action: `present_clue` -> `lin_qichi`
- Phase: `investigation`
- LLM success: `true`
- Schema valid: `true`
- Director blocked: `false`
- Block reason: `none`
- Disclosure claims: `1`
- Speech touched WorldInfo: `false`
- Missing disclosure claim: `false`
- Fallback used: `false`
- State unchanged: `true`

### Step 6: director blocks jiang medicine reveal before reconstruction

- Action: `talk` -> `jiang_yanhui`
- Phase: `confrontation`
- LLM success: `true`
- Schema valid: `true`
- Director blocked: `false`
- Block reason: `none`
- Disclosure claims: `0`
- Speech touched WorldInfo: `false`
- Missing disclosure claim: `false`
- Fallback used: `false`
- State unchanged: `true`

### Step 7: present lock marks updates only jiang awareness

- Action: `present_clue` -> `jiang_yanhui`
- Phase: `confrontation`
- LLM success: `true`
- Schema valid: `true`
- Director blocked: `false`
- Block reason: `none`
- Disclosure claims: `0`
- Speech touched WorldInfo: `false`
- Missing disclosure claim: `false`
- Fallback used: `false`
- State unchanged: `true`
