# QuantPay ID (`/id`)

Loki can hold and operate a QuantPay ID (QPID) directly. The holder key is generated inside the active Loki profile and the private JWK never leaves that profile.

## Commands

- `/id status` — show QPID, assurance, KYA, credential, mandate, and ERC-8004 state.
- `/id start [name]` — generate the holder key, create QPID1, and start Stripe Identity KYA.
- `/id continue` — after the human completes Stripe verification, issue QPID2 and complete OpenID4VCI holder-bound credential delivery.
- `/id test [merchant]` — create a USD 100 x402 mandate and prove deterministic authorization: USD 75 is allowed and USD 100.01 is denied.
- `/id bind <erc8004-id>` — bind/verify an already-created QuantPay Chain ERC-8004 registry entry.
- `/id doctor` — verify the public QuantPay ID issuer discovery endpoints.
- `/id open` — reprint the pending Stripe Identity verification URL.

## Authentication

`/id start` requires a QuantPay user bearer token because Stripe KYA must be associated with a real controller user. Store it in the active Loki profile's secret environment as `QUANTPAY_ACCESS_TOKEN`. Do not paste bearer tokens into chat or slash-command arguments.

Optional overrides:

- `QUANTPAY_API_URL` (default `https://quantpay.sh/v1`)
- `QUANTPAY_IDENTITY_ISSUER_URL` (default `https://id.quantpay.sh`)
- `QUANTPAY_API_KEY` (supported for non-KYA API operations)
- `QUANTPAY_ORGANIZATION_ID`

## Local state and key custody

The active profile stores QPID material under:

```text
$LOKI_HOME/identity/quantpay/
  holder.jwk       # ES256 / P-256 private holder key, mode 0600
  state.json       # lifecycle state, mode 0600
  credential.json  # holder-bound QuantPay Agent Credential, mode 0600
```

Only the public JWK is sent when the QPID agent is created. OpenID4VCI proof-of-possession and mandate action proofs are signed locally with `holder.jwk`.

## First production acceptance flow

```text
/id doctor
/id start Loki Production Agent
# Human opens the returned Stripe verification URL and completes KYA.
/id continue
/id test loki.computer
```

A successful test ends with:

```text
QPID deterministic authorization test: PASS
$75.00 -> ALLOW
$100.01 -> DENY (amount_limit_exceeded)
```

ERC-8004 registration is intentionally separate from holder-key custody. Once an on-chain registry entry exists, `/id bind <erc8004-id>` asks QuantPay to verify it against the configured QPC registry and the QPID agent URI.
