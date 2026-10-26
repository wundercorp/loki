# AgentVerified ID (`/id`)

Loki can enroll, hold, and operate an AgentVerified ID (QPID) directly. The holder key is generated inside the active Loki profile and the private JWK never leaves that profile.

## Commands

- `/id status` — show local/live QPID, assurance, KYA, credential, mandate, and ERC-8004 state.
- `/id start [name]` — generate the holder key and start a short-lived AgentVerified browser enrollment through Console.
- `/id continue` — exchange the approved device enrollment for an agent-bound management token, reconcile KYA, issue QPID2, and complete OpenID4VCI holder-bound credential delivery.
- `/id test [merchant]` — request a human-approved USD 100 x402 mandate. After Wallet/Console approval, prove deterministic authorization: USD 75 is allowed and USD 100.01 is denied.
- `/id bind <erc8004-id>` — bind/verify an already-created QuantPay Chain ERC-8004 registry entry.
- `/id doctor` — verify the public AgentVerified ID issuer discovery endpoints.
- `/id open` — reprint the pending Console approval URL.

## Enrollment authentication

`/id start` does **not** require the human's Cognito bearer token and does not ask the user to paste one into Loki.

The flow is intentionally device-like:

1. Loki generates/retains its P-256 holder key locally.
2. Loki sends only the public JWK to `POST /v1/agent-enrollments`.
3. AgentVerified returns a short-lived device code, human pairing code, and Console approval URL.
4. The human signs into AgentVerified in the browser and approves the agent.
5. If the controller already has a current verified identity session, AgentVerified reuses it. Otherwise the browser flow starts Stripe Identity.
6. `/id continue` signs a fresh holder JWT with `holder.jwk`, binds that proof to the device-code digest, and exchanges the approved device enrollment once for a `qpe_...` token bound to exactly that QPID with only `agents.read`, `agents.kya`, and `agents.mandate_request`. Possession of the device code alone is insufficient, and the token never receives `agents.write`.
7. Loki uses that scoped token to finish KYA and OpenID4VCI delivery. The normal human web session never enters Loki.

Optional endpoint overrides:

- `AGENTVERIFIED_API_URL` (default `https://agentverified.sh/v1`; legacy `QUANTPAY_API_URL` is still accepted)
- `AGENTVERIFIED_IDENTITY_ISSUER_URL` (default `https://id.agentverified.sh`; legacy `QUANTPAY_IDENTITY_ISSUER_URL` is still accepted)

`AGENTVERIFIED_ACCESS_TOKEN` and `AGENTVERIFIED_API_KEY` are preferred; legacy `QUANTPAY_ACCESS_TOKEN` and `QUANTPAY_API_KEY` remain supported for operator/development compatibility, but they are not required for the normal `/id start` enrollment path.

## Console approval

- **Console (`console.agentverified.sh`)** is the business/admin surface: workspace approval, agent administration, delegation/mandates, and business/KYB-backed QPID3. It reuses an eligible verified business session when available; otherwise approval falls back to controller KYC/QPID2. Console enrollment approval requires a business operator role (owner/admin/finance/manager); an ordinary member can still approve their own personal QPID2 enrollment but cannot attach an agent to business KYB. The Agent Harness includes a AgentVerified ID control plane listing QPIDs, assurance, payment methods, ERC-8004 binding, and KYA actions.

## Local state and key custody

The active profile stores QPID material under:

```text
$LOKI_HOME/identity/quantpay/
  holder.jwk             # ES256 / P-256 private holder key, mode 0600
  state.json             # lifecycle state, mode 0600
  management-token.json  # QPID-bound qpe_ bootstrap/management token, mode 0600
  credential.json        # holder-bound AgentVerified Agent Credential, mode 0600
```

Only the public JWK is sent during enrollment. Device-token exchange proof, OpenID4VCI proof-of-possession, and mandate action proofs are all signed locally with `holder.jwk`.

## First production acceptance flow

```text
/id doctor
/id start Loki Production Agent
# Open the returned AgentVerified approval URL, sign in, approve, and complete Stripe Identity only if required.
/id continue
/id test loki.computer
```

A successful authorization test ends with:

```text
QPID deterministic authorization test: PASS
$75.00 -> ALLOW
$100.01 -> DENY (amount_limit_exceeded)
```

ERC-8004 registration is intentionally separate from holder-key custody. Once an on-chain registry entry exists, `/id bind <erc8004-id>` asks AgentVerified to verify it against the configured QPC registry and the QPID agent URI.
