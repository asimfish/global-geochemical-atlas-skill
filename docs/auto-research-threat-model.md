# Auto-Research and adversarial-agent threat model

## Protected assets

- immutable atlas and loop-round bytes;
- source identity, license, version, record locators and scientific boundaries;
- claim-to-artifact SHA-256 bindings;
- local filesystem outside the selected research root;
- localhost controller token and user research question;
- manuscript, figure and review integrity; and
- the human publication decision.

External documents, downloaded data, browser input and every model result are
untrusted.  Filesystem workspaces provide auditable context separation; they are
not an operating-system sandbox and do not prove that two provider invocations
are statistically independent.

## Threats and controls

| Threat | Control | Residual boundary |
|---|---|---|
| Previous-round coaching or hidden review leakage | Scout/challenger/reviewer packets set `fresh_session_required=true`, enumerate the only allowed files and exclude memory, earlier verdicts, executor summaries and review prose. Packet-hash invariance is regression-tested against changed memory. Revision writers may see structured gate feedback; the next reviewer cannot. | The host must actually launch a fresh session. Same-family review is labelled provisional. |
| A role approves or scores itself | Scout and challenger cannot emit an admission or score; deterministic code scores frozen facts, and normal D1 gates plus a named human retain admission authority. Unique invocation IDs and role-bound envelopes are mandatory. | Human review can still be mistaken; hashes do not replace expertise. |
| Result or evidence tampering | Packets, inputs, result payloads, artifacts, fixed claims and receipts are SHA-256 bound and rehashed before each transition. Accepted role results are immutable. | SHA-256 proves byte identity, not truth, representativeness or causality. |
| Prompt injection from papers/data | Agent packets state that input is data, limit readable inputs and require structured outputs. Deterministic stages never execute downloaded code. | A model may still produce poor prose; the claim gate and independent review must reject it. |
| Path traversal or symlink escape | The controller derives run IDs from hashes, resolves every input/output below fixed roots, rejects absolute paths, symlink escapes and oversized artifacts. | The local account retains its normal OS permissions; run the service under an appropriately restricted account for hostile multi-user systems. |
| Browser CSRF or DNS rebinding | The controller binds only `127.0.0.1`, validates Host and Origin, requires a random fragment-delivered token, one-use nonce, JSON media type and a 16 KiB body limit, and emits no CORS grant. | Browser extensions or local malware with page access are outside this boundary. Stop the server after use. |
| Credential disclosure or arbitrary command execution | The page contains no provider key. The server accepts only four typed request fields and invokes fixed Python modules through argument lists with `shell=False`. | External agent hosts manage their own credentials outside GGA. |
| Fabricated completion or automatic publication | Missing agents remain `awaiting_agents`; failed review creates an immutable feedback-bound revision (maximum three) and then stops for human intervention; passing review ends at `awaiting_human_approval` with `publication_allowed=false`. Static pages only export a request. | Submission and scientific sign-off remain external human actions. |

## Security test obligations

Release tests must cover changed memory, wrong packet/role/input hashes, reused
invocation IDs, changed claim values, changed artifact bytes, unsupported
manuscript/figure claim IDs, duplicate review gates, traversal, hostile Host and
same-family review labelling.  Scanner success is supporting evidence only.
