# Merge C Pre-Merge Audit Verification

## ✅ Verified now (mock)
The following end-to-end integration tests have been written using `MockEndpoint` and verify the pipeline lifecycle according to Merge C fixes:

- **2a. Run completes, Judge picks the expected winner:** `test_merge_c_2a_run_completes_judge_picks_winner` (PASSED)
- **2b. KILL via CancelToken mid-run -> SQLite trace contains partial results:** `test_merge_c_2b_kill_mid_run` (PASSED)
- **2c. JSON repair cost accumulation equals trace total:** `test_merge_c_2c_json_repair_cost` (PASSED)
- **2d. Router routes correctly, raises error on unmatched:** `test_merge_c_2d_router_unmatched_condition` (PASSED)
- **2e. Serializer scrubSecrets and load back round-trip:** `test_merge_c_2e_serializer_scrub_secrets` (PASSED in Python schema dump) + `scrubSecrets removes api_key, token, and secret fields from pipeline` (PASSED in `serializer.test.ts`)

- **D1. Real streaming kill:** `test_ollama_d1_streaming_kill` (PASSED against Ollama qwen2.5:3b)
- **D2. Real malformed-JSON repair:** `test_ollama_d2_json_repair` (PASSED against Ollama qwen2.5:3b)
- **D3. Judge on genuine model output:** `test_ollama_d3_d4_judge_and_tokens` (PASSED against Ollama qwen2.5:3b)
- **D4. Cost accuracy & real token counts:** `test_ollama_d3_d4_judge_and_tokens` (PASSED against Ollama qwen2.5:3b)

## ⏳ Deferred (none)
All deferred items from Phase 3 have now been verified.
