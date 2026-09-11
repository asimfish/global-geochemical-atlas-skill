"""Draft a declarative adapter spec from a repair-queue gap and a table header.

This is the proposal half of the gap-to-data closure: when the self-correction
loop leaves ``skill_maintenance_new_run`` action groups (a discovered source
with no registered adapter), this tool turns the gap plus the candidate's
header row into a machine-fillable draft of
``references/declarative-adapter.schema.json``:

    python scripts/propose_adapter_spec.py \
        --from-repair-queue OUTPUT_DIR/d1_repair_queue.json --task-id ab12... \
        --candidate-url https://example.org/data.csv \
        --sniff --output adapter_proposals/spec-example.json

The draft is always ``approval_state: draft``. Promotion requires a human (or
an explicitly authorized policy) to fill the license id + evidence URL and set
``approved_by_operator`` / ``auto_candidate_open_license``. The proposal step
never downloads more than ``--sniff-bytes`` and never writes evidence; only
``declarative_adapter.py`` acquires data, behind its license and hash gates.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import urllib.request
from pathlib import Path
from typing import Any

PROPOSER_VERSION = "adapter-spec-proposer-v1"
DEFAULT_SNIFF_BYTES = 262144

ELEMENT_SYMBOLS = {
    "Ag",
    "Al",
    "As",
    "Au",
    "B",
    "Ba",
    "Be",
    "Bi",
    "Ca",
    "Cd",
    "Ce",
    "Co",
    "Cr",
    "Cs",
    "Cu",
    "Fe",
    "Ga",
    "Ge",
    "Hf",
    "Hg",
    "In",
    "K",
    "La",
    "Li",
    "Mg",
    "Mn",
    "Mo",
    "Na",
    "Nb",
    "Ni",
    "P",
    "Pb",
    "Rb",
    "S",
    "Sb",
    "Sc",
    "Se",
    "Sn",
    "Sr",
    "Ta",
    "Te",
    "Th",
    "Ti",
    "Tl",
    "U",
    "V",
    "W",
    "Y",
    "Yb",
    "Zn",
    "Zr",
}
LATITUDE_ALIASES = ("latitude", "lat", "lat_dd", "y", "decimallatitude", "lat_wgs84")
LONGITUDE_ALIASES = (
    "longitude",
    "lon",
    "long",
    "lon_dd",
    "x",
    "decimallongitude",
    "lon_wgs84",
)
SAMPLE_ALIASES = (
    "sample_id",
    "sampleid",
    "sample",
    "station",
    "site_id",
    "lab_id",
    "id",
)
METHOD_ALIASES = ("method", "analytical_method", "technique", "analysis_method")
UNIT_SUFFIXES = (
    ("_ppm", "ppm"),
    ("_mgkg", "mg/kg"),
    ("_mg_kg", "mg/kg"),
    ("_ugl", "ug/L"),
    ("_ug_l", "ug/L"),
    ("_ppb", "ppb"),
    ("_pct", "wt%"),
)


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:48] or "candidate"


def sniff_header(
    *, url: str | None, local_file: Path | None, sniff_bytes: int
) -> list[str]:
    if local_file is not None:
        data = local_file.read_bytes()[:sniff_bytes]
    elif url is not None:
        request = urllib.request.Request(
            url, headers={"User-Agent": "global-geochemical-atlas-spec-proposer/1"}
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            data = response.read(sniff_bytes)
    else:
        return []
    text = data.decode("utf-8", errors="replace")
    delimiter = (
        "\t"
        if text.splitlines()[0].count("\t") > text.splitlines()[0].count(",")
        else ","
    )
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    for row in reader:
        return [cell.strip() for cell in row]
    return []


def match_column(header: list[str], aliases: tuple[str, ...]) -> str | None:
    lowered = {column.lower(): column for column in header}
    for alias in aliases:
        if alias in lowered:
            return lowered[alias]
    return None


def propose_observations(
    header: list[str], wanted_elements: list[str]
) -> list[dict[str, str]]:
    observations: list[dict[str, str]] = []
    wanted = set(wanted_elements) or ELEMENT_SYMBOLS
    for column in header:
        base = column.strip()
        unit = None
        for suffix, mapped in UNIT_SUFFIXES:
            if base.lower().endswith(suffix):
                base = base[: -len(suffix)]
                unit = mapped
                break
        candidate = base.strip("_ ").capitalize()
        if candidate in ELEMENT_SYMBOLS and candidate in wanted:
            observations.append(
                {
                    "analyte": candidate,
                    "value_column": column,
                    "unit_constant": unit or "FILL_ME_UNIT",
                }
            )
    return observations


def load_gap(queue_path: Path, task_id: str | None) -> dict[str, Any] | None:
    queue = json.loads(queue_path.read_text(encoding="utf-8"))
    tasks = queue.get("tasks", [])
    task = None
    if task_id:
        task = next((t for t in tasks if t.get("task_id") == task_id), None)
    elif tasks:
        maintenance = [
            t for t in tasks if t.get("execution_class") == "skill_maintenance_new_run"
        ]
        pool = maintenance or tasks
        task = min(pool, key=lambda t: t.get("priority", 1 << 30))
    if task is None:
        return None
    return {
        "queue_version": queue.get("queue_version"),
        "request_sha256": queue.get("request_sha256"),
        "task_id": task.get("task_id"),
        "task_kind": task.get("task_kind"),
        "scope_key": task.get("scope_key"),
        "view_id": task.get("view_id"),
        "required_elements": task.get("required_elements"),
        "required_media": task.get("required_media"),
        "country_iso_a3": task.get("country_iso_a3"),
        "target_label": task.get("target_label"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-repair-queue", type=Path)
    parser.add_argument("--task-id")
    parser.add_argument("--candidate-url")
    parser.add_argument("--title")
    parser.add_argument("--official-url")
    parser.add_argument("--license-id")
    parser.add_argument("--license-evidence-url")
    parser.add_argument("--medium", choices=("rock", "soil", "sediment", "water"))
    parser.add_argument("--sniff", action="store_true")
    parser.add_argument("--sniff-bytes", type=int, default=DEFAULT_SNIFF_BYTES)
    parser.add_argument(
        "--local-file",
        type=Path,
        help="sniff a local sample file instead of the network",
    )
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    gap = None
    if args.from_repair_queue:
        gap = load_gap(args.from_repair_queue.resolve(), args.task_id)

    header: list[str] = []
    unresolved: list[str] = []
    if args.sniff:
        try:
            header = sniff_header(
                url=args.candidate_url,
                local_file=args.local_file.resolve() if args.local_file else None,
                sniff_bytes=args.sniff_bytes,
            )
        except Exception as exc:  # noqa: BLE001 - reported, never guessed around
            unresolved.append(f"sniff_failed: {exc}")

    wanted_elements = list((gap or {}).get("required_elements") or [])
    observations = propose_observations(header, wanted_elements) if header else []
    latitude = match_column(header, LATITUDE_ALIASES)
    longitude = match_column(header, LONGITUDE_ALIASES)
    sample = match_column(header, SAMPLE_ALIASES)
    method = match_column(header, METHOD_ALIASES)

    if not args.candidate_url:
        unresolved.append("download.url: no candidate URL supplied")
    if not args.license_id:
        unresolved.append(
            "license.id: must be filled from the publisher's license page"
        )
    if not args.license_evidence_url:
        unresolved.append("license.evidence_url: must point at the license evidence")
    if not observations:
        unresolved.append("mapping.wide_observations: no element columns recognized")
    if not args.medium:
        unresolved.append("medium.constant: choose the sampled medium")
    if latitude is None or longitude is None:
        unresolved.append("mapping.latitude/longitude columns not recognized")
    unresolved.append(
        "coordinate.crs_declared: only fill with publisher-declared CRS plus evidence URL"
    )
    unresolved.append(
        "dataset_version: fill the publisher version or an 'accessed YYYY-MM-DD' statement"
    )

    title = args.title or (gap or {}).get("target_label") or "FILL_ME_TITLE"
    spec = {
        "spec_version": "declarative-adapter-spec-v1",
        "source_id": "spec-" + slugify(str(title)),
        "title": title,
        "official_source_url": args.official_url
        or args.candidate_url
        or "https://FILL_ME",
        "dataset_doi": None,
        "dataset_version": "FILL_ME_VERSION_OR_ACCESSED_DATE",
        "license": {
            "id": args.license_id or "FILL_ME_LICENSE",
            "evidence_url": args.license_evidence_url or "https://FILL_ME",
        },
        "download": {
            "url": args.candidate_url or "https://FILL_ME",
            "max_bytes": 268435456,
            "expected_sha256": None,
        },
        "format": "csv",
        "layout": "wide",
        "medium": {"constant": args.medium} if args.medium else {"constant": "FILL_ME"},
        "mapping": {
            "wide_observations": observations
            or [
                {
                    "analyte": "FILL_ME",
                    "value_column": "FILL_ME",
                    "unit_constant": "FILL_ME",
                }
            ],
            "latitude_column": latitude,
            "longitude_column": longitude,
            "sample_id_column": sample,
            "method_column": method,
        },
        "coordinate": {"crs_declared": None, "crs_evidence_url": None},
        "row_filters": [],
        "target_gap": gap,
        "approval_state": "draft",
        "notes": (
            f"drafted by {PROPOSER_VERSION}; unresolved fields must be completed and "
            "reviewed before approval"
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "status": "draft_written",
                "output": str(args.output),
                "sniffed_columns": len(header),
                "proposed_observations": len(observations),
                "unresolved": unresolved,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
