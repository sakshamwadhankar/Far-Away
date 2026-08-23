# Governance-intercept demo

A scripted walkthrough for recording. The desktop automation is **real** —
real keystrokes, real deletion. Only the *choice* of action is scripted, via
the existing `MockEndpoint`, so no API key, quota or model quality can spoil a
take. Describe it as a scripted demo and it is accurate.

## Before recording

1. **Make a throwaway folder.** `press_key delete` sends it to the Recycle Bin,
   so a retake just means restoring it — but do not point this at anything you
   care about.
2. **Open File Explorer at the folder's parent** (e.g. `Downloads`) and click
   once in the file list so type-ahead has focus. The script starts from there.
3. **Switch the active governance profile to `review`.** This is essential:
   `locked` is all-`ENFORCE` and hard-denies with **no prompt**, so there would
   be nothing to film. `review` is all-`ASK`.
4. Leave `allow_destructive: false` on the access node — that is what triggers
   the gate.

## Run

Set both variables before starting the backend (the script is ignored unless
the mock gate is already open):

```
KOMVOS_ALLOW_MOCK_ENDPOINT=1
KOMVOS_MOCK_ACTION_SCRIPT=<repo>/docs/demo/governance-intercept.actions.json
```

Set the `computer_agent` node's endpoint to a `mock` endpoint, then send any
message in Use mode.

## Beat sheet

| Step | Action | On screen |
|------|--------|-----------|
| 1 | `type_text "DMGT"` | Explorer type-ahead selects the folder. No prompt — the classifier reads plain text as benign. |
| 2 | `press_key delete` | **Approval prompt fires.** The destructive gate catches it. Show the policy panel and decision trail here. |
| 3 | — | Approve on camera; the folder is deleted. |
| 4 | `done` | Run completes; monitor shows the finished run. |

Exactly one interception, landing on the delete. Approval timeout is 300s, so
there is no rush to click.

## Notes

- The script holds on its final entry rather than looping, so a trailing `done`
  ends the run cleanly.
- Adding navigation steps costs extra prompts: approvals are scoped per action
  type (`destructive:press_key`, `destructive:hotkey`, …) and the classifier
  fails safe on any keyboard action with no verified target. Opening Explorer
  beforehand is what keeps this to a single interception.
