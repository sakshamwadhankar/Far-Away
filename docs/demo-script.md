# Komvos Governance: Judge Demo Script

This unified demo script guides a judge through the core governance functionality of Komvos in under 2 minutes. It demonstrates how **one single pipeline** behaves differently across the three built-in governance profiles (**Explore**, **Review**, and **Locked**), with the immutable Decision Log proving the governance outcome in each case.

---

## Screen Requirements at a Glance
- **Steps 1–6 (Governance Dial & Tri-Profile Verification)**: Standard application canvas. Does **NOT** require a physical screen or OS automation permissions (runs with any configured LLM endpoint or local mock).
- **Step 7 (Optional Desktop Computer Automation)**: Requires `cua-computer-server` running on `http://127.0.0.1:8100` and an active display session.

---

## Preparation (Clean Install / Startup)
1. **Start the backend server:**
   ```bash
   cd backend
   ./.venv/Scripts/python.exe -m uvicorn komvos.api.main:app --port 8000
   ```
2. **Start the frontend:**
   ```bash
   cd apps/desktop
   npm run dev
   ```
3. **Open the application** in your browser (`http://localhost:5173`) or packaged Electron app.

---

## Walkthrough: One Pipeline Under Three Profiles

### Phase A: Load the Pipeline Template
1. In the top toolbar, open **Templates** and load **`Governance Approval Demo`** (from `templates/governance-approval.json`).
2. *Inspection:* Notice the `policy_gate` Access node specifies restricted permissions (`providers: ["ollama"]`, `allow_network: false`). The subsequent model node calls `openai:gpt-4o`. The pipeline policy intentionally withholds external cloud calls.

---

### Phase B: Run Under EXPLORE (Audit Posture)
1. **Click the Governance Indicator** in the bottom-left corner and click the **`EXPLORE`** profile card.
2. *Observation:* The indicator turns lime/green with `○` (Audit) glyphs.
3. **Click "▶ Run Pipeline"**.
4. *Observation:* The pipeline executes to completion without interruption.
5. **Open "🛡 History"** in the top toolbar:
   - **Outcome**: `✓ ALLOWED`
   - **Origin**: `Profile`
   - **Reason**: `Permitted by profile 'explore' audit posture despite a pipeline-policy denial`
   - *Proof:* The audit dial permitted exploratory execution while recording full accountability.

---

### Phase C: Run Under REVIEW (Ask Posture)
1. **Click the Governance Indicator** and select the **`REVIEW`** profile card.
2. *Observation:* The indicator turns amber (`#B8960A`) with `?` (Ask) glyphs.
3. **Click "▶ Run Pipeline"**.
4. *Observation:* Execution reaches the gated node and **pauses immediately**.
5. *Observation:* The **"Approval Required"** interactive prompt modal appears:
   - Displays the blocked capability: `providers:openai:gpt-4o`.
   - Explains why the pipeline policy withheld it.
   - Shows active countdown timer.
6. **Click "Allow Once"**.
7. *Observation:* The prompt dismisses, execution resumes, and the run completes.
8. **Open "🛡 History"**:
   - **Outcome**: `✓ ALLOWED`
   - **Origin**: `👤 Human · allow once`
   - **Reason**: Confirms the human operator explicitly authorized the single invocation.

---

### Phase D: Run Under LOCKED (Enforce Posture)
1. **Click the Governance Indicator** and select the **`LOCKED`** profile card.
2. *Observation:* The indicator turns red with `■` (Enforce) glyphs.
3. **Click "▶ Run Pipeline"**.
4. *Observation:* Execution immediately halts with an `AccessDeniedError`. No popup appears; no human is disturbed.
5. **Open "🛡 History"**:
   - **Outcome**: `✕ DENIED`
   - **Origin**: `Pipeline & Profile`
   - **Reason**: `Profile 'locked' upholds the pipeline's own policy for this domain.`
   - *Proof:* The strict posture failed closed without permitting ungranted capabilities.

---

## Summary of Observed Outcomes

| Profile | Posture | Execution Experience | History Log Outcome | History Origin |
| :--- | :--- | :--- | :--- | :--- |
| **EXPLORE** | Audit | Runs through uninterrupted | `ALLOWED` | `Profile` (Audit) |
| **REVIEW** | Ask | Suspends for human confirmation | `ALLOWED` | `Human · allow once` |
| **LOCKED** | Enforce | Fails closed immediately | `DENIED` | `Pipeline & Profile` |

---

## Step 7 (Optional): Governed Desktop Automation Demo
*Requires real screen & `cua-computer-server`.*

1. Start `cua-computer-server`:
   ```bash
   ./.venv/Scripts/python.exe -m computer_server --port 8100 --host 127.0.0.1
   ```
2. Load template **`Desktop Automation Demo`** (`templates/desktop-automation.json`).
3. Under **REVIEW**: The Computer node grounds UI marks on screen. Any sensitive or ungranted system action prompts the operator. Clicking **Allow Once** dispatches the mechanical action and runs post-action visual verification.
4. Under **LOCKED**: Ungranted desktop operations are rejected at the governance gate before any mouse click or keyboard input reaches the OS.
