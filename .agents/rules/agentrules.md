---
trigger: always_on
---

No dummy/fake/mock data in app code — call real APIs/endpoints. Fakes only in clearly-named test files.
No silent placeholders — never TODO then return True; raise an explicit error and report it.
No secrets in code or files — API keys come from the OS keychain via keyring; never hardcode or log them.
No hallucinated APIs — don't invent SDK methods/config; use official SDKs, say so if unsure.
Stay in your lane & honor contracts — only touch your assigned folders; never change a shared interface/schema/route without flagging a BREAKING CHANGE.
Types + tests mandatory — full type hints (pydantic/TS, no loose any); every feature ships with a test, lint/format must pass.
Always end your reply with: files changed, how to run, how to test, contracts touched, and any blockers.
