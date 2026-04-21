# OpenClaw / ClawHub service contracts

The OpenClaw ecosystem (Moltmail, Moltbook, MoltX, Clawk, Shellmates, the Ctxly suite, ClawTasks, dozens more) shares a family resemblance around agent-first signup:

- No human dashboard; signup is expected to happen from code running on behalf of an agent.
- Most use **EVM-compatible crypto wallets** (secp256k1) for identity. The agent generates a keypair, signs a nonce challenge, the service registers the public address.
- Several distribute their signup ceremony as a **ClawHub Skill** — a downloadable package that agents install via a runtime called `Clawdis`. The verifier does NOT have Clawdis today, and we don't plan to install it in the sandbox.
- API surfaces once authenticated are plain HTTPS + JSON, with a `Bearer <jwt>` header.

## Contract shape for OpenClaw services

Write the signup test as an ordinary `agent_task`. The prompt tells the Gemini-in-Daytona agent to do the wallet-signing inline with `ethers.js` or `viem` (both installable via `npm install`, which works in the default Daytona container). Do **not** depend on Clawdis or the skill package.

Minimum viable OpenClaw signup prompt fragment:

```
1. Inside the sandbox, run:
   npm install --silent ethers 2>/dev/null
2. Generate a fresh EVM keypair and store the private key ONLY in memory:
   const w = require('ethers').Wallet.createRandom();
3. POST <service>/nonce with {walletAddress: w.address}. Response: {nonce}.
4. Sign the message '<service's exact challenge string>\n\nNONCE: ${nonce}'
   with the private key. Use wallet.signMessage(message), NOT signing a hash.
5. POST <service>/authenticate with {web3Address, signature, ...platformData}
   to receive the JWT. Report it as <service>_jwt.
6. If the service has a first-login onboarding POST, call it with the JWT.
```

The agent runs that sequence, captures the JWT, and returns it via the structured output the `agent_task` step expects. No new contract primitives required.

## Why not implement `openclaw_skill_install` as a step?

It's tempting to add a primitive that downloads a ClawHub skill and runs it. Three reasons we don't:

1. **Skill integrity is untrusted input.** ClawHub distributes third-party packages that scan-as-Benign, but the verifier sandbox is our trust boundary. Arbitrary npm packages executed under a real wallet would be a bigger attack surface than the signup they're trying to test.
2. **It decouples "the service works" from "this skill works."** If a skill breaks, the service itself could still be agent-first — we'd report the wrong verdict.
3. **The Gemini agent can write the ceremony itself.** Every OpenClaw signup we've looked at is a thin wrapper around wallet gen + ECDSA sign + one or two HTTPS calls. Gemini can emit those ~30 lines of ethers.js directly.

If an OpenClaw service's signup genuinely CANNOT be expressed as a short inline ceremony — e.g. it requires a running Clawdis daemon with persistent state — the service is Tier 3 for our purposes. Report `failed` at signup with a note explaining the blocker. Don't paper over it.

## Reference: moltmail

See `verifier/contracts/moltmail.json`. It's an intentional Tier-3 marker right now because the signup endpoint returned 403 for ad-hoc signatures last time we probed it. If a later attempt reproduces the signature format successfully, rewrite the contract's `agent_task` prompt using the template above and requeue.

## When the auto-generator encounters an OpenClaw service

The generator prompt (`verifier/contract/generate.py`) includes an explicit guideline:

> *If the service is OpenClaw / ClawHub-based (crypto wallet, skill-install flow), still use agent_task in signup. The agent can do `npm install ethers` and generate a keypair + sign a challenge inside the sandbox. Document the wallet-signing steps plainly in the prompt. Do NOT assume a Clawdis runtime; write the crypto ops inline.*

If the LLM ever produces a contract that requires Clawdis or references a ClawHub skill package by URL, the validator rejects it.
