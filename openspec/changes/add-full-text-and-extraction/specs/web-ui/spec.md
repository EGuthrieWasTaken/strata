# web-ui Specification Delta

## ADDED Requirements

### Requirement: Extraction and risk-of-bias screens

The web UI MUST provide:

| Route | Purpose |
|---|---|
| `/extract/<study>` | The coding form |
| `/extract/<study>/reconcile` | Field-by-field reconciliation |
| `/rob/<study>` | Risk-of-bias instrument |

These screens MUST meet the same keyboard, accessibility, and security
requirements as the screening surface, and the coding form MUST make entering a
source locator a single keystroke.

_Source: `docs/spec/11-web-ui.md` §2; `docs/spec/03-schemas.md` §6_

#### Scenario: Reconciling in the browser

- **WHEN** a reconciler resolves a disagreement at `/extract/<study>/reconcile`
- **THEN** a `reconcile` event is recorded exactly as the CLI would record it
