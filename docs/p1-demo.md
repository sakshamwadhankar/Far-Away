# P1 Demo Path: Dialing Governance Profiles & Decision Audit Log

This 60-second demo proves that the Governance Profile dial effectively controls execution behavior and that the Decision History log captures every policy consequence and human approval.

1. **Locate the Governance Indicator in the bottom-left corner of the window.**
   - *Observation:* The indicator displays the active profile name (e.g., `LOCKED` or `EXPLORE`), a colored status dot, and domain posture glyphs (`■` for Enforce, `?` for Ask, `○` for Audit).

2. **Click the Governance Indicator to open the Profile Picker.**
   - *Observation:* The Profile Picker dial opens. It displays the built-in profiles (Explore, Review, Locked) and any custom profiles, showing postures for all five domains (Providers, Egress, Spend, Retention, Desktop), Recording Level (`Full` or `Metadata`), and Retention Window (`forever`, `30d`, etc.).

3. **In the Profile Picker, click the "REVIEW" profile card to activate it.**
   - *Observation:* The card activates with an active border. The bottom-left Governance Indicator immediately updates to `REVIEW` with an amber dot and `?` marks for Ask postures.

4. **Load the "Governance Approval Demo" seed template and click "▶ Run Pipeline".**
   - *Observation:* The pipeline begins executing. Because the pipeline's Access node withholds cloud provider access and the profile posture is **Ask**, execution suspends.
   - *Observation:* An interactive **"Approval Required"** prompt dialog interrupts the screen, showing the blocked capability (`providers:openai:gpt-4o`), detailed reason, and a 60-second countdown timer.

5. **In the Approval Prompt, click "Allow Once".**
   - *Observation:* The prompt dismisses immediately, execution resumes, and the pipeline completes successfully.

6. **Click the "🛡 History" button in the top toolbar.**
   - *Observation:* The Decision History table opens.
   - *Observation:* The top row records the human decision:
     - **Domain**: `providers`
     - **Outcome**: `✓ ALLOWED`
     - **Origin**: `👤 Human · allow once`
     - **Reason**: Explains the manual operator approval overriding the pipeline policy denial.

7. **Close History, click the bottom-left Governance Indicator, and select "LOCKED".**
   - *Observation:* The active profile switches to `LOCKED`. The indicator turns red with `■` enforce marks.

8. **Click "▶ Run Pipeline" again.**
   - *Observation:* The pipeline executes and immediately halts with an `AccessDeniedError`. No approval popup appears because `LOCKED` enforces policy immediately.

9. **Click "🛡 History" once more.**
   - *Observation:* The latest row displays:
     - **Domain**: `providers`
     - **Outcome**: `✕ DENIED`
     - **Origin**: `Pipeline & Profile` (or `Profile`)
     - **Reason**: Confirms the profile's Enforce posture upheld the pipeline denial without human interruption.
