# packaging

**Owner: P1 + P2 (shared — packaging is a joint Phase 4 deliverable)**

## Purpose

Scripts and configuration for building signed, distributable installers of the
NeuralFlow desktop application.

## Strategy (TRD §1)

- **Python runtime:** embedded via **PyInstaller** — users do not need Python
  installed.
- **Electron:** bundled by `electron-builder` (or equivalent) into platform
  installers.
- **macOS:** signed + **notarized** (Apple Gatekeeper requirement).
- **Windows:** code-signed (Microsoft SmartScreen requirement).
- **Linux:** best-effort AppImage.

## Planned contents

| File / folder (planned) | Purpose |
| :--- | :--- |
| `pyinstaller.spec` | PyInstaller spec file for the FastAPI backend bundle. |
| `electron-builder.yml` | Electron builder configuration for all three platforms. |
| `scripts/sign-mac.sh` | macOS codesign + notarytool wrapper. |
| `scripts/sign-win.ps1` | Windows `signtool` wrapper. |
| `scripts/build-all.sh` | Orchestrates PyInstaller → Electron build → sign on CI. |

> **This directory is intentionally empty for now.**
> Packaging scripts will be written in Phase 4 (Merge D / release candidate).
> No placeholder scripts are committed — see AGENT.md rule 2.

## CI requirements (Phase 4)

- macOS runner with an Apple Developer certificate + notarization credentials
  in the CI keychain.
- Windows runner with a code-signing certificate.
- Both must build the full installer end-to-end as the Merge D acceptance gate.
