#!/usr/bin/env python3
"""Verify the candidate commit and hashes named by test-repository-identity.json."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath


SHA256_RE = re.compile(r"[0-9a-f]{64}")
COMMIT_RE = re.compile(r"[0-9a-f]{40}")


class IdentityError(RuntimeError):
    pass


def git(root: Path, *args: str, binary: bool = False) -> str | bytes:
    completed = subprocess.run(
        ["git", "-C", str(root), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        message = completed.stderr.decode("utf-8", errors="replace").strip()
        raise IdentityError(f"git {' '.join(args)} failed: {message}")
    return completed.stdout if binary else completed.stdout.decode("utf-8").strip()


def blob(root: Path, commit: str, relative: str) -> bytes:
    path = PurePosixPath(relative)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise IdentityError(f"unsafe repository-relative path: {relative!r}")
    return git(root, "show", f"{commit}:{path.as_posix()}", binary=True)  # type: ignore[return-value]


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def git_blobs(root: Path, object_ids: list[str]) -> list[bytes]:
    process = subprocess.Popen(
        ["git", "-C", str(root), "cat-file", "--batch"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert process.stdin is not None
    assert process.stdout is not None
    assert process.stderr is not None
    process.stdin.write("".join(f"{object_id}\n" for object_id in object_ids).encode("ascii"))
    process.stdin.close()
    bodies: list[bytes] = []
    for expected_id in object_ids:
        header = process.stdout.readline().decode("ascii", errors="strict").rstrip("\n")
        fields = header.split(" ")
        if len(fields) != 3 or fields[0] != expected_id or fields[1] != "blob":
            process.kill()
            raise IdentityError(f"unexpected git cat-file header: {header!r}")
        size = int(fields[2])
        body = process.stdout.read(size)
        terminator = process.stdout.read(1)
        if len(body) != size or terminator != b"\n":
            process.kill()
            raise IdentityError(f"truncated git blob stream for {expected_id}")
        bodies.append(body)
    return_code = process.wait(timeout=30)
    if return_code != 0:
        message = process.stderr.read().decode("utf-8", errors="replace").strip()
        raise IdentityError(f"git cat-file --batch failed: {message}")
    return bodies


def candidate_tree_entries(root: Path, commit: str, subtree: str | None = None) -> list[tuple[str, bytes]]:
    args = ["ls-tree", "-rz", "--full-tree", "-r", commit]
    if subtree is not None:
        args.extend(["--", subtree])
    raw = git(root, *args, binary=True)
    assert isinstance(raw, bytes)
    metadata: list[tuple[str, str]] = []
    for record in raw.split(b"\0"):
        if not record:
            continue
        header, encoded_path = record.split(b"\t", 1)
        mode, kind, object_id = header.decode("ascii").split(" ")
        if kind != "blob" or mode not in {"100644", "100755"}:
            raise IdentityError(f"candidate contains unsupported entry: {encoded_path!r} {mode} {kind}")
        metadata.append((encoded_path.decode("utf-8"), object_id))
    bodies = git_blobs(root, [object_id for _path, object_id in metadata])
    return [(path, body) for (path, _object_id), body in zip(metadata, bodies, strict=True)]


def e1_tree_sha256(root: Path, commit: str, subtree: str) -> str:
    prefix = PurePosixPath(subtree).as_posix().rstrip("/") + "/"
    digest = hashlib.sha256()
    entries = candidate_tree_entries(root, commit, subtree)
    for path, body in sorted(entries, key=lambda item: item[0]):
        if not path.startswith(prefix):
            raise IdentityError(f"Skill entry escaped subtree: {path}")
        relative = path[len(prefix) :]
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(len(body)).encode("ascii"))
        digest.update(b"\0")
        digest.update(body)
        digest.update(b"\0")
    if not entries:
        raise IdentityError("candidate Skill tree is empty")
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--identity",
        type=Path,
        default=Path("evaluation/results/validation/test-repository-identity.json"),
    )
    parser.add_argument("--require-remote", action="store_true")
    args = parser.parse_args()
    identity_path = args.identity.resolve()
    repository_root = Path(git(identity_path.parent, "rev-parse", "--show-toplevel"))
    identity = json.loads(identity_path.read_text(encoding="utf-8"))
    errors: list[str] = []

    repository = identity.get("repository", {})
    skill = identity.get("production_skill", {})
    evaluation = identity.get("evaluation", {})
    sizes = identity.get("size_evidence", {})
    commit = repository.get("candidate_commit")
    if not isinstance(commit, str) or not COMMIT_RE.fullmatch(commit):
        errors.append("candidate_commit is not a 40-character lowercase Git commit")
    else:
        try:
            observed_tree = git(repository_root, "rev-parse", f"{commit}^{{tree}}")
            if observed_tree != repository.get("candidate_git_tree"):
                errors.append("candidate Git tree mismatch")
            skill_path = skill.get("relative_path")
            if not isinstance(skill_path, str):
                errors.append("production Skill relative_path is invalid")
            else:
                observed_skill_git_tree = git(repository_root, "rev-parse", f"{commit}:{skill_path}")
                if observed_skill_git_tree != skill.get("git_tree"):
                    errors.append("production Skill Git tree mismatch")
                observed_skill_sha = e1_tree_sha256(repository_root, commit, skill_path)
                if observed_skill_sha != skill.get("tree_sha256"):
                    errors.append("production Skill E1 tree SHA-256 mismatch")

            for path_key, sha_key in (
                ("freeze_manifest", "freeze_manifest_sha256"),
                ("package_validation", "package_validation_sha256"),
            ):
                relative = evaluation.get(path_key)
                expected = evaluation.get(sha_key)
                if not isinstance(relative, str) or not isinstance(expected, str) or not SHA256_RE.fullmatch(expected):
                    errors.append(f"invalid {path_key}/{sha_key} identity")
                    continue
                body = blob(repository_root, commit, relative)
                if sha256(body) != expected:
                    errors.append(f"{path_key} SHA-256 mismatch")
                if path_key == "freeze_manifest":
                    manifest = json.loads(body)
                    if manifest.get("content_manifest_sha256") != evaluation.get("evaluation_content_manifest_sha256"):
                        errors.append("evaluation content manifest SHA-256 mismatch")

            tracked_bytes = sum(len(body) for _path, body in candidate_tree_entries(repository_root, commit))
            if tracked_bytes != sizes.get("candidate_tracked_blob_bytes"):
                errors.append("candidate tracked byte count mismatch")
            limit = sizes.get("limit_bytes_exclusive")
            if not isinstance(limit, int) or tracked_bytes >= limit:
                errors.append("candidate tracked bytes do not satisfy the exclusive repository limit")

            if args.require_remote:
                branch = repository.get("candidate_branch")
                url = repository.get("url")
                if not isinstance(branch, str) or not isinstance(url, str):
                    errors.append("remote repository URL or candidate branch is invalid")
                else:
                    remote = subprocess.run(
                        ["git", "ls-remote", url, f"refs/heads/{branch}"],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        check=False,
                    )
                    remote_commit = remote.stdout.split()[0] if remote.returncode == 0 and remote.stdout.split() else None
                    if remote_commit != commit:
                        errors.append("remote candidate branch is absent or does not point to candidate_commit")
        except (IdentityError, json.JSONDecodeError, OSError, ValueError) as exc:
            errors.append(str(exc))

    report = {
        "schema_version": "gga.test-repository-identity-audit.v1",
        "candidate_commit": commit,
        "remote_checked": args.require_remote,
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
    }
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
