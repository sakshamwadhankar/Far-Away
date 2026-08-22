# Phase 2 Demo — Governed Desktop Automation: REVIEW vs LOCKED

This guide provides a reproducible walkthrough demonstrating how the Komvos governance engine controls the **Computer node** under the **REVIEW** (Ask) and **LOCKED** (Enforce) governance profiles.

---

## 1. Setup & Environment
1. Launch the backend service:
   ```bash
   cd backend
   ./.venv/Scripts/python.exe -m uvicorn komvos.api.main:app --port 8000
   ```
2. In a second terminal, launch the desktop frontend:
   ```bash
   cd apps/desktop
   npm run dev
   ```
3. Open the Komvos application window in your browser or Electron shell.

---

## 2. Canvas Construction: Building a Governed Desktop Pipeline
1. In the left sidebar palette under **Node Types**, drag an **Input** node onto the canvas.
2. Drag a **Computer** node (`🖥`) onto the canvas.
3. Drag an **Access** node (`⛨`) onto the canvas between the Input and Computer nodes.
4. Drag an **Output** node onto the canvas.
5. Connect the nodes:
   - `Input [prompt]` ➔ `Access` ➔ `Computer [task]`
   - `Computer [result]` ➔ `Output [response]`
6. Configure the **Access** node:
   - Click the Access node to view its capability list.
   - Leave `Desktop Control` and `Destructive Actions` **unchecked (denied)** to simulate a restrictive boundary.
7. Configure the **Computer** node:
   - Set the `endpoint_ref` to an active vision model (e.g. `anthropic:claude-3-5-sonnet-20241022` or `openai:gpt-4o`).
   - Set the prompt input to: `"Open settings and clear temporary cache files."`

---

## 3. Scenario A: Executing under the REVIEW Profile (Ask Posture)

### Expected Behavior:
Under the **REVIEW** profile, the `desktop` domain is configured with the **Ask** posture. When the pipeline reaches the Computer node attempting a desktop action without an explicit policy grant, execution **suspends** and requests operator confirmation.

### Step-by-Step Execution:
1. Click the **Profile Indicator** in the bottom-left corner of the app and select the **REVIEW** profile.
2. Click **▶ Run Pipeline**.
3. **Observation — Loop Execution**:
   - The Computer node captures the initial screen state and overlays Set-of-Marks badges.
   - The model selects an action that targets system settings.
   - The classifier detects a destructive / system setting action (`category="system_security"`).
4. **Observation — Interactive Approval Prompt**:
   - Execution immediately pauses.
   - An **Approval Prompt** dialog appears with the message:
     > *"Node 'computer-1' requires desktop control / destructive action, which its access policy does not grant."*
   - Three choices are presented:
     1. **Allow Once**: Permits this single step and continues the loop.
     2. **Allow for Run**: Grants the capability for the remainder of this execution run.
     3. **Deny**: Rejects the action and halts the node with an `AccessDeniedError`.
5. Click **Allow Once**:
   - The action executes against the desktop layer.
   - The verifier validates the resulting visual delta.
   - The decision is logged in **🛡 History** with `outcome: "allow"` and `origin: "human_approval"`.

---

## 4. Scenario B: Executing under the LOCKED Profile (Enforce Posture)

### Expected Behavior:
Under the **LOCKED** profile, the `desktop` domain is configured with the **Enforce** posture. The pipeline's access policy is strictly enforced. Any unauthorized desktop control or ungranted destructive action is immediately **denied and halted** without human intervention.

### Step-by-Step Execution:
1. Click the **Profile Indicator** and switch the active profile to **LOCKED**.
2. Click **▶ Run Pipeline**.
3. **Observation — Immediate Enforcement**:
   - The Computer node attempts to initiate desktop control.
   - The governance gate consults the **LOCKED** posture.
   - Because the upstream Access node does not grant `allow_desktop`, the governance gate **denies** the action immediately.
   - No approval popup is displayed.
   - The node fails with `AccessDeniedError: Node 'computer-1' (computer) requires desktop control, which its access policy does not grant.`
4. **Observation — Audit Trail**:
   - Open **🛡 History** from the top toolbar.
   - A decision record appears:
     - **Domain**: `desktop`
     - **Capability**: `allow_desktop`
     - **Outcome**: `DENY`
     - **Origin**: `pipeline_policy`
     - **Reason**: `Posture ENFORCE: pipeline policy withheld permission.`

---

## 5. Reviewing Open Source Licences & Attributions
1. Click the **📜 Licences** button in the top toolbar.
2. Verify that:
   - **CC-BY-4.0** attribution is prominent and links to the official license terms.
   - All third-party components (including `cua-computer-server`, `FastAPI`, `React`, `React Flow`, and `Pydantic`) are accurately documented.
