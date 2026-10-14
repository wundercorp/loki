# QuantPay ID (`/id`)

Loki can enroll, hold, and operate a QuantPay ID (QPID) directly. The holder key is generated inside the active Loki profile and the private JWK never leaves that profile.

## Commands

- `/id status` — show local/live QPID, assurance, KYA, credential, mandate, and ERC-8004 state.
- `/id start [name]` — generate the holder key and start a short-lived QuantPay browser enrollment. Defaults to Wallet for an individual controller.
- `/id start --console [name]` — use Console as the human approval surface. Console reuses eligible business/KYB evidence for QPID3 when available, otherwise it falls back to controller KYC/QPID2.
- `/id continue` — exchange the approved device enrollment for an agent-bound management token, reconcile KYA, issue QPID2, and complete OpenID4VCI holder-bound credential delivery.
- `/id test [merchant]` — request a human-approved USD 100 x402 mandate. After Wallet/Console approval, prove deterministic authorization: USD 75 is allowed and USD 100.01 is denied.
- `/id bind <erc8004-id>` — bind/verify an already-created QuantPay Chain ERC-8004 registry entry.
- `/id doctor` — verify the public QuantPay ID issuer discovery endpoints.
- `/id open` — reprint the pending Wallet/Console approval URL.

## Enrollment authentication

`/id start` does **not** require the human's Cognito bearer token and does not ask the user to paste one into Loki.

The flow is intentionally device-like:

1. Loki generates/retains its P-256 holder key locally.
2. Loki sends only the public JWK to `POST /v1/agent-enrollments`.
3. QuantPay returns a short-lived device code, human pairing code, and Wallet/Console approval URLs.
4. The human signs into QuantPay in the browser and approves the agent.
5. If the controller already has a current verified identity session, QuantPay reuses it. Otherwise the browser flow starts Stripe Identity.
6. `/id continue` signs a fresh holder JWT with `holder.jwk`, binds that proof to the device-code digest, and exchanges the approved device enrollment once for a `qpe_...` token bound to exactly that QPID with only `agents.read`, `agents.kya`, and `agents.mandate_request`. Possession of the device code alone is insufficient, and the token never receives `agents.write`.
7. Loki uses that scoped token to finish KYA and OpenID4VCI delivery. The normal human web session never enters Loki.

Optional endpoint overrides:

- `QUANTPAY_API_URL` (default `https://quantpay.sh/v1`)
- `QUANTPAY_IDENTITY_ISSUER_URL` (default `https://id.quantpay.sh`)

`QUANTPAY_ACCESS_TOKEN` and `QUANTPAY_API_KEY` remain supported for operator/development compatibility, but they are not required for the normal `/id start` enrollment path.

## Wallet vs Console

- **Wallet (`wallet.quantpay.sh`)** is the default personal-controller surface: sign-in, agent approval, and individual identity verification for QPID2. A current verified identity session is reusable across agents.
- **Console (`console.quantpay.sh`)** is the business/admin surface: workspace approval, agent administration, delegation/mandates, and business/KYB-backed QPID3. It reuses an eligible verified business session when available; otherwise approval falls back to controller KYC/QPID2. Console enrollment approval requires a business operator role (owner/admin/finance/manager); an ordinary member can still approve their own Wallet/QPID2 enrollment but cannot attach an agent to business KYB. The Agent Harness includes a QuantPay ID control plane listing QPIDs, assurance, payment methods, ERC-8004 binding, and KYA actions.
- Both surfaces call the same backend enrollment and verification records; they do not maintain separate KYC copies.

## Local state and key custody

The active profile stores QPID material under:

```text
$LOKI_HOME/identity/quantpay/
  holder.jwk             # ES256 / P-256 private holder key, mode 0600
  state.json             # lifecycle state, mode 0600
  management-token.json  # QPID-bound qpe_ bootstrap/management token, mode 0600
  credential.json        # holder-bound QuantPay Agent Credential, mode 0600
```

Only the public JWK is sent during enrollment. Device-token exchange proof, OpenID4VCI proof-of-possession, and mandate action proofs are all signed locally with `holder.jwk`.

## First production acceptance flow

```text
/id doctor
/id start Loki Production Agent
# Open the returned Wallet URL, sign in, approve, and complete Stripe Identity only if required.
/id continue
/id test loki.computer
```

For a Console approval surface:

```text
/id start --console Loki Production Agent
```

A successful authorization test ends with:

```text
QPID deterministic authorization test: PASS
$75.00 -> ALLOW
$100.01 -> DENY (amount_limit_exceeded)
```

ERC-8004 registration is intentionally separate from holder-key custody. Once an on-chain registry entry exists, `/id bind <erc8004-id>` asks QuantPay to verify it against the configured QPC registry and the QPID agent URI.
