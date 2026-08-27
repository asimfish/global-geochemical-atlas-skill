# Three-layer adversarial source-audit contract

Every pending D1 action group with governed candidate facts can be projected to
an immutable audit under `OUTPUT_DIR/agent_audits/round-.../`.

- **Scout** nominates source IDs from the frozen candidate set and lists missing
  evidence. It cannot score, admit or issue a final verdict.
- **Challenger** attacks identity, access, research-use license, version/file
  integrity, region, medium and record locators. It sees frozen candidate facts,
  not scout scratch or a previous verdict.
- **Judge** is deterministic Python. It validates both role envelopes and then
  computes the 10-point rubric from frozen boolean facts only: official identity
  2, machine access 2, research-use license 2, version/integrity 1, region 1,
  medium 1, locator 1. Scores at least 7 create an integration draft, 4-6 request
  supplements, and below 4 rejects the candidate. All routes still require D1
  gates and human approval; `admitted` remains false.

Previous memory is fingerprinted only in the selection receipt and is excluded
from both evaluator packets. Tests prove that changing only memory leaves both
packet hashes unchanged. Each result binds role, round, unique invocation ID,
model family, packet hash, exact input hashes, payload hash and envelope hash.
Wrong roles, unknown inputs, reused invocations and changed bytes fail closed.

When a D1 group has no registered candidate, the manifest records
`awaiting_candidate_discovery`; an empty agent vote is never manufactured. Run
the group’s declared discovery plan, register evidence through normal D1 review,
then prepare the adversarial audit.
