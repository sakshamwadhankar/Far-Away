# Phase 2 Demo — Governed Desktop Automation: REVIEW vs LOCKED

This guide provides a reproducible walkthrough demonstrating how the Komvos governance engine controls the **Computer node** under the **REVIEW** (Ask) and **LOCKED** (Enforce) governance profiles.

---

## 1. Setup & Environment
1. Start the desktop automation server:
   ```bash
   cd backend
   ./.venv/Scripts/python.exe -m computer_server --port 8100 --host 127.0.0.1
   ```
2. In a second terminal, launch the backend API service:
   ```bash
   cd backend
   ./.venv/Scripts/python.exe -m uvicorn komvos.api.main:app --port 8000
   ```
3. In a third terminal, launch the desktop frontend:
   ```bash
   cd apps/desktop
   npm run dev
   ```
4. Open the Komvos application window in your browser or desktop shell.

---

## 2. Pipeline Loading
1. Load the pre-configured seed template: `Desktop Automation Demo` (located in `templates/desktop-automation.json`).
2. The pipeline structure:
   - **Input Node (`in`)**: provides the desktop task prompt (e.g. `"Open settings and clear temporary cache files."`).
   - **Access Node (`policy_boundary`)**: scoped policy marker defining allowed applications and withholding destructive permissions.
   - **Computer Node (`computer_agent`)**: connects to the vision model and local `cua-computer-server` execution layer.
   - **Output Node (`out`)**: displays the execution outcome.
   - Data flow: `in.task` ➔ `computer_agent.task` ➔ `out.result`.

---

## 3. Scenario A: Executing under the REVIEW Profile (Ask Posture)

### Expected Behavior:
Under **REVIEW**, the `desktop` domain posture is **Ask**. When the Computer node attempts an action requiring desktop control or targeting an ungranted destructive capability, execution **suspends** and requests operator confirmation.

### Step-by-Step Execution:
1. Click the **Governance Indicator** in the bottom-left corner and select the **REVIEW** profile.
2. Click **▶ Run Pipeline**.
3. **Observation — Screen Grounding & Gating**:
   - The Computer node captures screen state and overlays Set-of-Marks grounding badges.
   - The vision model selects a desktop action targeting system settings.
   - The classifier detects a system setting / destructive operation (`category="system_security"`).
4. **Observation — Interactive Approval Prompt**:
   - Execution pauses immediately.
   - The **Approval Prompt** dialog appears with the message:
     > *"Destructive action 'click' withheld: Target is system/security setting"*
   - Options presented:
     1. **Allow Once**: Permits this single action and resumes loop.
     2. **Allow for Run**: Grants the capability for the remainder of this run.
     3. **Deny**: Rejects the action and halts the node with `AccessDeniedError`.
5. Click **Allow Once**:
   - The mechanical action executes via the local `cua-computer-server`.
   - The post-action verifier computes visual delta and records verification.
   - The decision is logged in **🛡 History** with `outcome: "allow"` and `origin: "human_allow_once"`.

---

## 4. Scenario B: Executing under the LOCKED Profile (Enforce Posture)

### Expected Behavior:
Under **LOCKED**, the `desktop` domain posture is **Enforce**. The pipeline's access policy is strictly enforced: any ungranted desktop control or destructive action is immediately **denied and halted** without human intervention.

### Step-by-Step Execution:
1. Click the bottom-left **Governance Indicator** and switch the active profile to **LOCKED**.
2. Click **▶ Run Pipeline**.
3. **Observation — Immediate Fail-Closed Enforcement**:
   - The Computer node reaches the governance gate.
   - Because the policy withholds permission for destructive operations and the profile posture is **Enforce**, the gate immediately halts execution.
   - No approval popup is displayed.
   - The pipeline fails safely with an `AccessDeniedError`.
4. **Observation — Audit Trail**:
   - Open **🛡 History** from the top toolbar.
   - A decision record appears:
     - **Domain**: `desktop`
     - **Capability**: `destructive:click` (or `allow_desktop`)
     - **Outcome**: `DENIED`
     - **Origin**: `Pipeline & Profile`
     - **Reason**: Confirms the profile enforced the withholding without human interaction.

---

## 5. Reviewing Open Source Licences & Attributions
1. Click the **📜 Licences** button in the top toolbar.
2. Verify that:
   - **CC-BY-4.0** attribution is prominent and links to official terms.
   - All third-party components (including `cua-computer-server`, `FastAPI`, `React`, `React Flow`, and `Pydantic`) are accurately documented.
