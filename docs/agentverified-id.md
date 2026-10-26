# AgentVerified ID (`/id`)

Loki keeps the AgentVerified holder private key locally under `$LOKI_HOME/identity/agentverified/`. The private JWK is never uploaded.

## Commands

- `/id status` — show local identity state and live management status when connected.
- `/id start [name]` — first-time AgentVerified enrollment. If an identity already exists, Loki refuses to create another one and points to `/id reconnect`.
- `/id reconnect` — restore Loki's scoped management connection to the existing AgentVerified ID. This does not create a new Agent ID, replace the holder key, replace the credential, or repeat identity verification.
- `/id continue` — finish the pending first-time enrollment or reconnect approval.
- `/id open` — reprint the pending browser approval URL.
- `/id doctor` — verify the public issuer/discovery endpoints.

## Reconnecting an existing identity

If `/id status` shows `Identity ready` together with `Management connection: inactive`, run:

```text
/id reconnect
# approve the browser prompt
/id continue
```

Reconnect is fail-closed. Loki sends the existing public holder JWK plus its stored Agent ID/AVID to AgentVerified. The server only creates a reconnect session if that public key matches the existing identity. After human approval, Loki proves possession of the same private holder key before a fresh scoped management token is returned.

Loki verifies that the token exchange returns the exact same internal agent ID and AVID already stored locally. A mismatch is rejected before the new management token is saved.

The following local material is preserved byte-for-byte during reconnect:

- `holder.jwk`
- `credential.json`
- existing Agent ID / AVID
- assurance level
- prior identity-verification state

Reconnect does not invoke Stripe Identity for an already-created AgentVerified ID.
