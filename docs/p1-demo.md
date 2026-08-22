# P1 Demo Path

This 60-second demo proves that the Profile Picker effectively dials the application's behavior and the Decision History log audibly captures the consequence of that dial, including manual approvals.

1. **Click the top-right Governance Indicator ("LOCKED" or "EXPLORE").**
   - *You should see:* The Profile Picker dial slides into view. It displays three built-in profiles (Explore, Review, Locked) and any existing custom profiles. Each profile lists its postures (e.g., Enforce, Ask, Audit) and consequences (e.g., "Deny and halt").

2. **In the Profile Picker, click the "REVIEW" profile card to activate it.**
   - *You should see:* The card gains a green highlight boundary. The Governance Indicator in the top-right immediately updates to say "REVIEW" and displays a yellow dot and '?' indicators for its 'Ask' postures.

3. **Click the "▶ Run Pipeline" button.**
   - *You should see:* The pipeline begins executing. Very quickly, the run pauses, and an "Approval Required" overlay interrupts your screen. The prompt clearly states which domain (e.g., "Egress") and capability is blocked, and provides a countdown timer.

4. **In the Approval Prompt, click the "Allow Once" action.**
   - *You should see:* The prompt overlay disappears immediately, and the pipeline resumes running and completes.

5. **Click the "🛡 History" button in the top bar.**
   - *You should see:* The Decision History panel opens. 
   - *You should see:* The top row in the log reflects the action you just took. The Outcome column shows a solid pill saying "✓ ALLOWED". The Origin column shows a bolded human icon (👤) reading "Human · allow once", indicating a judge approved the step manually.

6. **Click the "X" on the History Panel, open the Profile Picker again, and click "LOCKED".**
   - *You should see:* The Profile Picker dial closes, the top-right indicator turns red and says "LOCKED".

7. **Click "▶ Run Pipeline" again.**
   - *You should see:* The pipeline runs and immediately fails/halts without asking for permission, because "LOCKED" enforces policy instead of asking.

8. **Click the "🛡 History" button once more.**
   - *You should see:* The newest row shows "✕ DENIED" with a dashed red border, and the Origin reads "Profile", proving the profile intervened automatically.
