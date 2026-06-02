# LLM Shadow Eval Report: mist_clock_manor

- Scenario: `cases\mist_clock_manor\scenarios\standard_path.yaml`
- Backend: `stub`
- Real shadow enabled: `false`
- State unchanged: `true`

## Summary

- total_shadow_calls: `6`
- schema_failure_count: `1`
- director_block_count: `4`
- missing_disclosure_claim_count: `1`
- speech_touched_world_info_count: `2`
- mode_violation_count: `2`
- full_reveal_block_count: `1`
- fallback_count: `5`
- skipped_count: `0`
- state_unchanged: `true`
- failure_category.director.blocked: `4`
- failure_category.disclosure.full_reveal: `1`
- failure_category.disclosure.unknown_world_info: `1`
- failure_category.fallback.used: `5`
- failure_category.schema.invalid: `1`
- failure_category.schema.invalid.unsupported_action: `1`
- failure_category.schema.invalid.validationerror: `1`
- failure_category.speech.directness_exceeds_mode: `1`
- failure_category.speech.missing_disclosure_claim: `1`
- failure_category.speech.world_info_touch_blocked: `1`

## Steps

### Step 1: compliant_hint

- Action: `ask_about` -> `lin_qichi`
- Phase: `opening`
- LLM success: `true`
- Schema valid: `true`
- Director blocked: `false`
- Block reason: `none`
- Disclosure claims: `1`
- Speech touched WorldInfo: `false`
- Missing disclosure claim: `false`
- Fallback used: `false`
- State unchanged: `true`

### Step 2: full_reveal_block

- Action: `ask_about` -> `lin_qichi`
- Phase: `opening`
- LLM success: `true`
- Schema valid: `true`
- Director blocked: `true`
- Block reason: `Disclosure claim for world_info 'sedative_wine' attempted full reveal`
- Disclosure claims: `1`
- Speech touched WorldInfo: `false`
- Missing disclosure claim: `false`
- Fallback used: `true`
- State unchanged: `true`

### Step 3: claim_compliant_but_speech_direct_block

- Action: `ask_about` -> `lin_qichi`
- Phase: `opening`
- LLM success: `true`
- Schema valid: `true`
- Director blocked: `true`
- Block reason: `Speech directness 'direct_claim' exceeds disclosure mode 'hint'`
- Disclosure claims: `1`
- Speech touched WorldInfo: `true`
- Missing disclosure claim: `false`
- Fallback used: `true`
- State unchanged: `true`

### Step 4: missing_disclosure_claim_block

- Action: `ask_about` -> `lin_qichi`
- Phase: `opening`
- LLM success: `true`
- Schema valid: `true`
- Director blocked: `true`
- Block reason: `Speech touched world_info 'timed_lock_modified' without a disclosure claim`
- Disclosure claims: `0`
- Speech touched WorldInfo: `true`
- Missing disclosure claim: `true`
- Fallback used: `true`
- State unchanged: `true`

### Step 5: invented_world_info_id_block

- Action: `ask_about` -> `lin_qichi`
- Phase: `opening`
- LLM success: `true`
- Schema valid: `true`
- Director blocked: `true`
- Block reason: `Disclosure claim for world_info 'invented_world_info' has no allowed constraint`
- Disclosure claims: `1`
- Speech touched WorldInfo: `false`
- Missing disclosure claim: `false`
- Fallback used: `true`
- State unchanged: `true`

### Step 6: unsupported_proposed_action_schema_failure

- Action: `ask_about` -> `lin_qichi`
- Phase: `opening`
- LLM success: `false`
- Schema valid: `false`
- Director blocked: `false`
- Block reason: `none`
- Disclosure claims: `0`
- Speech touched WorldInfo: `false`
- Missing disclosure claim: `false`
- Fallback used: `true`
- State unchanged: `true`
