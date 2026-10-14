# Loki QuantPay ID `/id` checkpoint — 2026-10-14

## Added

- Core `/id` command in Loki's canonical slash-command registry.
- CLI, gateway/messaging, autocomplete, help/menu, Telegram and native Slack integration.
- Profile-scoped QuantPay secret resolution through Loki's existing `.env`/secret boundary.
- Local ES256/P-256 holder-key generation with private JWK mode 0600.
- QPID1 creation with public-JWK-only registration.
- Stripe Identity KYA bootstrap and resumable verification URL.
- `/id continue` for authoritative KYA credential issuance and OpenID4VCI pre-authorized-code flow.
- Holder JWT proof signed locally and bound to the registered QPID public key.
- Holder credential saved locally with mode 0600.
- `/id test [merchant]` deterministic USD 100 x402 mandate acceptance test:
  - USD 75 -> ALLOW
  - USD 100.01 -> DENY (`amount_limit_exceeded`)
- `/id bind <erc8004-id>` for verifying/binding an existing QPC ERC-8004 registry entry.
- `/id doctor` for JWKS/OpenID4VCI/OAuth discovery checks.
- `/id open` and `/id status` lifecycle helpers.

## Security boundaries

- QuantPay access tokens are never accepted as `/id` arguments and are never written to QPID state.
- Private holder JWK is never included in QuantPay create/update payloads.
- OpenID4VCI access token/nonces are ephemeral and are not persisted.
- KYA must use a user bearer token; service API keys are not treated as a human controller identity.
- State, credential, and holder key files are mode 0600 under the active Loki profile.
- Gateway execution uses Loki's scope-aware secret reader to avoid cross-profile credential leakage.

## Cross-surface command catalog

Slack is capped at 50 native slash commands. `/id` is kept native; the low-frequency `/curator` command is routed through `/loki curator` on Slack to preserve Telegram/Slack parity. CLI and Telegram are unaffected.

## Validation

Focused suite:

```text
111 passed
```

Includes command registry/help/autocomplete/gateway dispatch and QPID lifecycle tests. The dedicated QPID suite is 4/4 passing.

`ruff` was not installed in the execution environment, so ruff lint was not run. Python compilation and the focused pytest suite passed.
