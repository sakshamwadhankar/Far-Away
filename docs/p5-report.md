# Phase 5: Computer Screenshot Outputs & Live UI Visuals Report

- **Declared Output Port Name & Type**:
  - Port name: `last_screenshot`
  - Port type: `image`
  - Aligned on Computer node executor (`backend/komvos/executors/computer.py`), default node definition in `apps/desktop/src/panels/LeftSidebar.tsx`, and template `templates/desktop-automation.json`.

- **Screenshot Downscaling Dimensions & Storage Size**:
  - Downscaled dimensions: Max width **1024px** (preserving aspect ratio, e.g., 1024×576 for 16:9 or 1024×640 for 16:10).
  - Compression: JPEG quality **75** with `optimize=True`.
  - Storage & payload size: **~35 KB – 50 KB** per screenshot (Base64 string length ~45 KB – 65 KB), reducing storage footprint by >95% compared to raw multi-megabyte PNG screenshots while preserving clear readability of UI text and grounding mark labels.

- **Live Screenshot UI Surfaces**:
  - **Trace Modal (`apps/desktop/src/panels/TraceModal.tsx`)**: Replaced raw stringified JSON output blobs with formatted responsive `<img>` previews for `last_screenshot` and image-typed output fields.
  - **Live Monitor Panel (`apps/desktop/src/panels/MonitorPanel.tsx`)**: Embedded "👁 Live Agent Vision" side-by-side pane rendering the latest grounded screenshot with numbered mark badges live as the agent observes and executes.
  - **Governance Approval Modal (`apps/desktop/src/governance/ApprovalPrompt.tsx`)**: Displays the target screen with numbered marks directly above approval actions whenever human-in-the-loop authorization is requested.

- **Evidence that LOCKED Does Not Persist Screenshots**:
  - Under `LOCKED` profile, `profile.retention == RetentionMode.METADATA`.
  - In `backend/komvos/state/sqlite.py` (`StateManager.save_node_execution` and `StateManager.save_loop_iteration`), metadata retention forces `inputs_json = "{}"` and `outputs_json = "{}"`.
  - SQLite query verification confirms:
    - `EXPLORE` (Full retention): `outputs_json` contains full base64 screenshot (`len = 154` chars in test fixture).
    - `LOCKED` (Metadata retention): `outputs_json = "{}"`, writing **0 bytes** of screenshots or raw payload data to the SQLite database.
