# P1B Report

- `apps/desktop/src/governance/ProfilePicker.tsx`
- `apps/desktop/src/governance/DecisionHistory.tsx`
- `apps/desktop/src/governance/ApprovalPrompt.tsx`

- **Profile Picker:** Opened via the ActiveProfileIndicator fixed to the top right of the viewport.
- **Decision History:** Opened via the new "🛡 History" button in the top bar.
- **Approval Prompt:** Displayed as a modal overlay in the center of the screen blocking interaction when a run suspends awaiting approval.

- **Form:** Specific glyphs are prefixed to the text (✓ for ALLOWED, ✕ for DENIED, ⏱ for TIMEOUT).
- **Outcome styling:** Uses pill badges with dotted/dashed borders (Timeout: dotted, Deny: dashed, Allow: solid) in addition to colors.

- **Origin column styling:** Human origins are bolded, styled in the accent color, and prefixed with a '👤' glyph to make them stand out from automated policy/profile decisions.
- **Row styling:** The table row itself has a distinct subtle background highlight if the decision was human-made.

- `npm run typecheck`: Passed
- `npm run lint`: Passed
- `npm test`: Passed (63 tests)

- No unsupported API features were encountered. All backend requirements for the governance UI matched the provided API client.

- NA. The provided components and constraints were clear.
