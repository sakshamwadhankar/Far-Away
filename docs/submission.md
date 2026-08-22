# Komvos Governance & Governed Desktop Automation: Final Submission

## 1. What the Feature Is
Komvos Governance is a local, policy-as-code and human-in-the-loop oversight engine designed for multi-model AI workflows and autonomous desktop automation.

Modern LLM pipelines and desktop agents operate with varying degrees of autonomy, making unconstrained execution dangerous and rigid total lockdown impractical for development. Komvos solves this by separating **pipeline-level policy** (what the author authored) from the **user's active governance dial** (how strict the operator wants the runtime to be).

The engine enforces boundaries across five distinct domains:
1. **Providers**: Restricts LLM calls to authorized model endpoints (e.g. local Ollama vs cloud providers).
2. **Egress**: Controls outbound network requests and domain allowlists.
3. **Spend**: Enforces USD budget ceilings and ask thresholds.
4. **Retention**: Regulates recording depth (`full` vs `metadata`) and retention window (`30d`, `forever`, etc.).
5. **Desktop**: Gates autonomous OS automation (Set-of-Marks grounding, pre-action destructive classification, mechanical execution, and post-action visual verification).

---

## 2. The One Behavior the User Adjusts
The user adjusts a single high-level control: the **Governance Profile Dial**.

Users can switch between three built-in profiles or configure custom ones:
- **`EXPLORE` (Audit Posture)**: Relaxed exploratory mode. Permissions denied by the pipeline policy are permitted under audit logging for fast iteration.
- **`REVIEW` (Ask Posture)**: Supervised human-in-the-loop mode. Any withheld capability suspends the run in real time and presents an interactive approval modal to the operator (`Allow Once`, `Allow for Run`, `Deny`).
- **`LOCKED` (Enforce Posture)**: Strict fail-closed production default. Any withheld capability immediately denies and halts execution with zero human interruptions.

---

## 3. How Core Requirements Are Satisfied

### State
- Governance profiles and active selections are persisted in local SQLite storage via `StateManager`.
- Default profile is strictly `LOCKED`, ensuring existing installations fail safe across upgrades.
- Missing, corrupted, or upgrading profiles default to `retention_window="forever"` to prevent unexpected data loss on startup.

### Feedback
- **Active Profile Indicator**: Pinned permanently at the bottom-left corner of the interface, displaying profile name, color-coded status dot, and domain posture glyphs (`■` Enforce, `?` Ask, `○` Audit).
- **Interactive Approval Modal**: Real-time WebSocket suspension event rendering domain, capability, reasoning, and timeout countdown.
- **Visual Feedback**: Real-time token streaming and execution monitor highlighting node status transitions.

### History
- **Immutable Decision History**: Full audit table capturing sequential records (`seq`, `timestamp_ms`, `domain`, `capability`, `outcome`, `origin`, `reason`, `effective_policy`, `governed_by`).
- Distinguishes exact origins: `pipeline_policy`, `profile`, `pipeline_and_profile`, `human_allow_once`, `human_allow_for_run`, `human_deny`.

---

## 4. Judge Click Path: Quick Confirmation
To verify all three dimensions in under 2 minutes:
1. **Explore Verification**:
   - Set Profile to **`EXPLORE`** (bottom-left indicator).
   - Load template **`Governance Approval Demo`** and click **▶ Run Pipeline**.
   - Open **🛡 History**: observe `✓ ALLOWED` with origin `Profile` (Audit).
2. **Review Verification**:
   - Set Profile to **`REVIEW`**.
   - Click **▶ Run Pipeline**: observe run suspends and approval prompt appears.
   - Click **Allow Once**: observe run completes.
   - Open **🛡 History**: observe `✓ ALLOWED` with origin `👤 Human · allow once`.
3. **Locked Verification**:
   - Set Profile to **`LOCKED`**.
   - Click **▶ Run Pipeline**: observe immediate fail-closed `AccessDeniedError`.
   - Open **🛡 History**: observe `✕ DENIED` with origin `Pipeline & Profile`.

---

## 5. Honest Limitations
- **Single-User Local Architecture**: Komvos is designed as a local desktop workstation tool. It does not provide multi-tenant team management, centralized enterprise directory authentication, or cloud-synchronized global policies.
- **No Formal Compliance Certification**: While Komvos implements defense-in-depth access controls, audit trails, and fail-closed gates, it has not undergone formal SOC2, HIPAA, or ISO27001 regulatory certifications.
- **Vision Model Quality Dependency**: Desktop agent reasoning and Set-of-Marks interpretation rely on the underlying vision model's multimodal accuracy. Complex custom canvas UIs with no accessibility metadata may require multiple steps or fallback grid navigation.
- **Headless Desktop Limitations**: In non-interactive background sessions or headless virtualized environments lacking a native Windows GDI display context, direct OS screen capture fails with `OSError: screen grab failed`. The architecture gracefully falls back to structured synthetic viewport grounding in such environments, but live screen automation requires an interactive user desktop session.
