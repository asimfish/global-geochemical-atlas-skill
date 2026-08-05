# P04 handoff summary

Status: `NOT_READY` (implementation present; production inputs and G0 evidence missing)

## Completed

- Repository/package/max-file measurement with JSON and Markdown reports.
- Dependency/import/lockfile/cold-start-risk inventory.
- HTTP(S) host allowlist, finite retry, MIME and byte limits, SHA-256, parser/field checks, atomic `.part` publication, and machine-readable errors.
- ZIP traversal, symlink, encryption, expansion-size, member-count, and compression-ratio defenses.
- Content-addressed immutable cache with `_COMPLETE.json`; cached mode verifies source version, URL, hash, schema, and read-only mode bits.
- Isolated `online`, `cached`, and `fixture` materialization. Existing run directories are never overwritten.
- Fixture outputs force `pipeline demonstration only; not for scientific interpretation` and `scientific_use_allowed=false`.
- USGS FDSN and GBIF Occurrence v1 source adapters, license/source documentation, user CSV demo, and good/bad fixtures.
- Fault tests for offline/403/transient HTTP, wrong MIME, disguised HTML, interrupted transfer, hash/schema/version drift, cache pollution, unsafe ZIPs, adapter errors, and empty-home cold start.
- A concurrently added container scaffold was preserved and reviewed; its seven host-side smoke tests pass, but no container engine is usable in this environment.

## Reproduce

```bash
python3 -s eval/environment/verify_p04.py
```

Expected exit code: `0`. The command returns `status=NOT_READY` while all locally provable checks pass; this distinction prevents missing production evidence from being reported as a successful integration gate.

Fixture smoke:

```bash
python3 -s -m eval.download.acquire \
  --mode fixture \
  --registry eval/fixtures/data/datasets.json \
  --dataset-id user-csv-demo \
  --output-dir /tmp/p04-fixture
```

Expected exit code: `0`; detailed evidence is in `checks.json`.

## Remaining integration blockers

1. Run the audit inside the production Git worktree to measure Git objects and tracked/untracked large files.
2. Supply the production Skill and dependency/lock files, then repeat dependency, license, wheel, and cold-start checks.
3. Obtain G0 network/resource approval before executing live USGS/GBIF online smoke; freeze the accepted response digest before B0/S0 cached runs.
4. Run the pinned image build and container smoke in an approved Docker/BuildKit environment; Docker is absent here and rootless Podman cannot create its user namespace.
5. Review and remove `tmp/feishu_auth_qr.png` from the submission package.

`READY_FOR_INTEGRATION` is deliberately absent until these blockers are closed.
