# Loki + QuantPay ID human-approval checkpoint — 2026-10-14

## Why this iteration

The original `/id start` required a pre-existing human `QUANTPAY_ACCESS_TOKEN`, which meant the command could not actually bootstrap a new user/agent. The first browser-enrollment iteration removed that dependency, but still needed stronger consent and delegation boundaries. This iteration completes those boundaries.

## Loki behavior

- `/id start [name]` creates a short-lived QuantPay device enrollment using only Loki's public holder JWK.
- The private P-256 JWK stays under the active Loki home at mode 0600.
- Default approval surface is Wallet; `/id start --console [name]` uses Console.
- The human must explicitly approve the agent after sign-in; browser sign-in no longer silently attaches an agent.
- `/id continue` exchanges the approved device code for a one-time-issued `qpe_...` bearer token server-bound to the single enrolled QPID, and the exchange itself requires a fresh holder JWT signed by Loki's local key and bound to the device-code digest.
- The human Cognito access token is never copied into Loki.
- `/id continue` completes KYA and OpenID4VCI holder-proof issuance with the local holder key.
- `/id test [merchant]` cannot self-create spending authority. It first creates a short-lived mandate request and returns a Wallet/Console approval URL. After human approval, rerunning `/id test` proves USD 75 ALLOW / USD 100.01 DENY under the human-approved USD 100 x402 mandate.
- `/id bind` remains a principal/admin action when Loki is using a `qpe_...` token.

## QuantPay device enrollment

- `POST /v1/agent-enrollments` — public; accepts public JWK and returns device/user codes plus Wallet/Console URLs.
- `GET /v1/agent-enrollments/:userCode` — public enrollment status/details.
- `POST /v1/agent-enrollments/:userCode/approve` — signed-in human explicitly approves and reuses/starts eligible KYC/KYB.
- `POST /v1/agent-enrollments/:userCode/cancel` — signed-in human declines the pending enrollment.
- `POST /v1/agent-enrollments/token` — one-time device-code exchange; requires a fresh holder JWT signed by the enrollment key and bound to the device-code digest, then returns plaintext `qpe_...` once while storing only its hash. Possession of the device code alone is insufficient.

The QPID-bound `qpe_...` scope set is exactly:

- `agents.read`
- `agents.kya`
- `agents.mandate_request`

It deliberately does **not** include `agents.write`. A regression test enforces this exact scope set.

## Human-approved mandate requests

- `POST /v1/agents/:id/mandate-requests` — QPID-bound agent asks for bounded authority.
- `GET /v1/agent-mandate-requests/:requestCode` — public request status/details.
- `POST /v1/agent-mandate-requests/:requestCode/approve` — signed-in authorized principal creates the actual bounded mandate.
- `POST /v1/agent-mandate-requests/:requestCode/decline` — signed-in authorized principal declines; no authority is created.

Mandate request audit data retains the enrollment-session ID that initiated the request. The agent cannot raise the merchant scope, amount cap, payment methods, or validity window after human approval.

## Product surfaces

- Wallet is the canonical individual-controller approval/KYC surface for QPID2.
- Console is the business/admin surface. It prefers a current verified business/KYB session and can therefore approve at QPID3; if no eligible business verification exists, it falls back to controller KYC/QPID2. Console enrollment approval requires owner/admin/finance/manager, while Wallet individual approval may be completed by the member/controller. Console Agent Harness now exposes the QPID list and KYA controls directly.
- Both surfaces explicitly show pairing/request codes and the authority being requested before approval.
- Both surfaces reuse current verification evidence when eligible instead of forcing Stripe Identity again for every agent.

## Validation

- QuantPay TypeScript no-emit/API build: passed.
- QuantPay credential/identity/holder-proof/Stripe/OpenID4VCI + enrollment-scope regression suite: 22/22 passed.
- Loki dedicated QPID lifecycle suite: 7/7 passed.
- Loki impacted command/gateway suite: 257 passed, 1 skipped (pre-existing Slack AsyncMock warnings only).
- Cross-language Loki Python enrollment proof -> QuantPay TypeScript verifier: passed.
- Wallet JS syntax check: passed.
- Console JSX TypeScript transpile/syntax check: passed.

A full Vite production web build could not be completed in this container because web dependency installation timed out and `vite` was not available afterward. The modified browser sources parse successfully; run the normal repository `npm ci` / production web build in the release environment before deployment.
