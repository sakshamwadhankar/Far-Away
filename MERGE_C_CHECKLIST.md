# Merge C Pre-Merge Audit Verification

## ✅ Verified now (mock)
The following end-to-end integration tests have been written using `MockEndpoint` and verify the pipeline lifecycle according to Merge C fixes:

- **2a. Run completes, Judge picks the expected winner:** `test_merge_c_2a_run_completes_judge_picks_winner` (PASSED)
- **2b. KILL via CancelToken mid-run -> SQLite trace contains partial results:** `test_merge_c_2b_kill_mid_run` (PASSED)
- **2c. JSON repair cost accumulation equals trace total:** `test_merge_c_2c_json_repair_cost` (PASSED)
- **2d. Router routes correctly, raises error on unmatched:** `test_merge_c_2d_router_unmatched_condition` (PASSED)
- **2e. Serializer scrubSecrets and load back round-trip:** `test_merge_c_2e_serializer_scrub_secrets` (PASSED in Python schema dump) + `scrubSecrets removes api_key, token, and secret fields from pipeline` (PASSED in `serializer.test.ts`)

## ⏳ Deferred (needs real model via Ollama)
These checks require a genuine model and have been deferred to Phase 4:
- real network latency / streaming kill on a real 30s call
- real (not scripted) malformed-JSON repair behavior
- Judge on genuine model output
- cost accuracy against a real provider pricing table
