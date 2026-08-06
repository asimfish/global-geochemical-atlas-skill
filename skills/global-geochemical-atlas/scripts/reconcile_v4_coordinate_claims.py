#!/usr/bin/env python3
"""Separate reported coordinates from canonical EPSG:4326 V4 coverage claims."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
PROFILE_ROOT = SKILL_DIR / "assets" / "v4-full-profiles"
CUBE_PATH = SKILL_DIR / "assets" / "v4-coverage-cube.csv"
BALANCE_PATH = SKILL_DIR / "assets" / "v4-coverage-balance.json"
REPORT_PATH = SKILL_DIR / "references" / "v4-full-population-profile.md"
MANIFEST_PATH = PROFILE_ROOT / "manifest.json"

NON_CANONICAL = {
    "georoc-archaean": "withheld_pending_datum_verification",
    "afsis-phase-i-wet-chemistry": "withheld_source_crs_not_reported",
    "japan-gsj-geochemical-map": "withheld_no_full_profile_coordinate_transform",
}
SOURCE_MEDIA = {
    "georoc-archaean": "rock",
    "afsis-phase-i-wet-chemistry": "soil",
    "japan-gsj-geochemical-map": "sediment",
}
SOURCE_ELEMENTS = {
    "georoc-archaean": {"As", "Cu", "Ni", "Zn"},
    "afsis-phase-i-wet-chemistry": {"As", "Cr", "Cu", "Ni", "Pb", "Zn"},
    "japan-gsj-geochemical-map": {"As", "Cr", "Cu", "Hg", "Ni", "Pb", "Zn"},
}
CLAIM_BOUNDARY = (
    "Counts describe target observations in one verified source snapshot. Reported coordinates are kept "
    "separate from canonical EPSG:4326 coordinates; only canonical cells enter cross-source spatial coverage. "
    "Cells are observed, not interpolated; comparable means the minimum declared V4 grouping fields are present."
)


class ReconciliationError(RuntimeError):
    """Raised when checked-in V4 artifacts cannot be reconciled safely."""


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="", dir=path.parent, delete=False) as handle:
        handle.write(value)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ReconciliationError(f"expected JSON object: {path}")
    return value


def _spatial_outputs() -> tuple[dict[Path, str], dict[str, dict[str, Any]]]:
    outputs: dict[Path, str] = {}
    spatial: dict[str, dict[str, Any]] = {}
    for source_dir in sorted(path for path in PROFILE_ROOT.iterdir() if path.is_dir()):
        source_id = source_dir.name
        for path in sorted(source_dir.glob("*.json")):
            value = _load_json(path)
            value["claim_boundary"] = CLAIM_BOUNDARY
            if path.name == "spatial_coverage.json":
                reported_samples = int(
                    value.get("reported_coordinate_sample_count", value["valid_coordinate_sample_count"])
                )
                reported_cells = int(value.get("reported_covered_spatial_cells", value["covered_spatial_cells"]))
                reported_ids = list(value.get("reported_spatial_cell_ids", value.get("spatial_cell_ids", [])))
                value.update(
                    reported_coordinate_sample_count=reported_samples,
                    reported_covered_spatial_cells=reported_cells,
                    reported_spatial_cell_ids=reported_ids,
                    reported_spatial_grid="source-coordinate 1-degree floor cell; not cross-source comparable",
                    coordinate_count_definition=(
                        "reported_coordinate_sample_count is numeric and range-valid in source coordinates; "
                        "valid_coordinate_sample_count additionally requires canonical EPSG:4326"
                    ),
                    spatial_grid="canonical EPSG:4326 1-degree floor cell; no interpolation",
                    coordinate_canonicalization_status=(
                        NON_CANONICAL.get(source_id, "source_crs_declared_epsg4326")
                    ),
                )
                if source_id in NON_CANONICAL:
                    value.update(
                        valid_coordinate_sample_count=0,
                        covered_spatial_cells=0,
                        spatial_cell_ids=[],
                        bbox=None,
                    )
                if source_id == "georoc-archaean":
                    denominator = sum(int(item) for item in value["source_crs_observation_counts"].values())
                    value["source_crs_observation_counts"] = {"not_reported": denominator}
                spatial[source_id] = value
            outputs[path] = _json_text(value)
    return outputs, spatial


def _cube_output() -> tuple[str, list[dict[str, str]], bool]:
    with CUBE_PATH.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        original_fields = list(reader.fieldnames or [])
        rows = list(reader)
    if not rows:
        raise ReconciliationError("coverage cube is empty")
    already_canonical = "reported_coordinate_sample_count" in original_fields and all(
        row["valid_coordinate_sample_count"] == "0"
        and row["comparable_observation_count"] == "0"
        and row["covered_spatial_cells"] == "0"
        for row in rows
        if row["source_id"] in NON_CANONICAL
    )
    fields = original_fields or list(rows[0])
    if "reported_coordinate_sample_count" not in fields:
        fields.insert(fields.index("valid_coordinate_sample_count"), "reported_coordinate_sample_count")
    for row in rows:
        reported = row.get("reported_coordinate_sample_count") or row["valid_coordinate_sample_count"]
        row["reported_coordinate_sample_count"] = reported
        row["spatial_grid"] = "canonical EPSG:4326 1-degree floor cell; observation coverage only"
        if row["source_id"] in NON_CANONICAL:
            row["valid_coordinate_sample_count"] = "0"
            row["comparable_observation_count"] = "0"
            row["covered_spatial_cells"] = "0"
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue(), rows, already_canonical


def _balance_output(
    spatial: Mapping[str, Mapping[str, Any]], *, already_canonical: bool
) -> tuple[str, dict[str, Any]]:
    balance = _load_json(BALANCE_PATH)
    for metrics in [*balance["media"].values(), *balance["medium_elements"].values()]:
        metrics["reported_coordinate_sample_count"] = int(
            metrics.get("reported_coordinate_sample_count", metrics["valid_coordinate_sample_count"])
        )
        metrics["reported_covered_spatial_cells"] = int(
            metrics.get("reported_covered_spatial_cells", metrics["covered_spatial_cells"])
        )
        metrics["reported_comparable_observation_count"] = int(
            metrics.get("reported_comparable_observation_count", metrics["comparable_observation_count"])
        )
        metrics["spatial_grid"] = "canonical EPSG:4326 1-degree floor cell; no interpolation"
    if not already_canonical:
        for metrics in [*balance["media"].values(), *balance["medium_elements"].values()]:
            metrics["valid_coordinate_sample_count"] = metrics["reported_coordinate_sample_count"]
            metrics["covered_spatial_cells"] = metrics["reported_covered_spatial_cells"]
            metrics["comparable_observation_count"] = metrics["reported_comparable_observation_count"]
        for source_id in NON_CANONICAL:
            medium = SOURCE_MEDIA[source_id]
            reported_samples = int(spatial[source_id]["reported_coordinate_sample_count"])
            reported_cells = int(spatial[source_id]["reported_covered_spatial_cells"])
            medium_metrics = balance["media"][medium]
            medium_metrics["valid_coordinate_sample_count"] -= reported_samples
            medium_metrics["covered_spatial_cells"] -= reported_cells
            if source_id == "afsis-phase-i-wet-chemistry":
                medium_metrics["comparable_observation_count"] -= 11256
            for element in SOURCE_ELEMENTS[source_id]:
                metrics = balance["medium_elements"].get(f"{medium}|{element}")
                if not isinstance(metrics, dict):
                    continue
                metrics["valid_coordinate_sample_count"] -= reported_samples
                metrics["covered_spatial_cells"] -= reported_cells
                if source_id == "afsis-phase-i-wet-chemistry":
                    metrics["comparable_observation_count"] -= reported_samples
    balance["claim_boundary"] = (
        "More observations do not imply broader coverage. Reported source coordinates and canonical EPSG:4326 "
        "coverage are separate; independent lineage, sample type, method and region must be interpreted together."
    )
    return _json_text(balance), balance


def _report(manifest: Mapping[str, Any]) -> str:
    lines = [
        "# V4 全量字段与覆盖立方体报告",
        "",
        "> 本报告由固定缓存全量解析生成；来源报告坐标与 canonical EPSG:4326 坐标分开统计，不使用 demo 行数替代全量分母。",
        "",
        "## 总览",
        "",
        f"- 全量 profile 来源：{manifest['source_count']}/{manifest['registered_source_count']}",
        f"- 目标元素测定：{manifest['observation_count']:,}",
        f"- 不同样品（逐来源去重后相加）：{manifest['distinct_sample_count']:,}",
        f"- 来源报告坐标样品：{manifest['reported_coordinate_sample_count']:,}",
        f"- canonical EPSG:4326 坐标样品：{manifest['valid_coordinate_sample_count']:,}",
        f"- 可比较测定：{manifest['comparable_observation_count']:,}",
        f"- 来源内 canonical 1° 观测格网数之和：{manifest['covered_spatial_cells_source_sum']:,}",
        f"- 覆盖立方体行：{manifest['coverage_cube_rows']:,}",
        "",
        "## 介质平衡",
        "",
        "| 介质 | 测定 | 样品 | 独立血缘 | 来源坐标样品 | canonical 坐标样品 | 可比较测定 | canonical 1°格网 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for medium, metrics in manifest["media"].items():
        lines.append(
            f"| {medium} | {metrics['observation_count']:,} | {metrics['distinct_sample_count']:,} | "
            f"{metrics['independent_lineage_count']:,} | {metrics['reported_coordinate_sample_count']:,} | "
            f"{metrics['valid_coordinate_sample_count']:,} | {metrics['comparable_observation_count']:,} | "
            f"{metrics['covered_spatial_cells']:,} |"
        )
    lines.extend(
        [
            "",
            "## 分来源",
            "",
            "| 来源 | 介质 | 测定 | 样品 | 来源坐标样品 | canonical 坐标样品 | 可比较测定 | canonical 1°格网 | 方法完整率 |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for source in manifest["sources"]:
        lines.append(
            f"| `{source['source_id']}` | {source['medium']} | {source['observation_count']:,} | "
            f"{source['distinct_sample_count']:,} | {source['reported_coordinate_sample_count']:,} | "
            f"{source['valid_coordinate_sample_count']:,} | {source['comparable_observation_count']:,} | "
            f"{source['covered_spatial_cells']:,} | {source['method_rate']:.1%} |"
        )
    lines.extend(
        [
            "",
            "## 解释边界",
            "",
            "- 来源坐标只证明数值完整且在经纬度范围内；datum/CRS 未证实时不会进入 canonical 地图。",
            "- `comparable_observation_count` 要求数值、单位、样品类型、canonical 坐标、measurement basis、方法与 method scope 同时存在。",
            "- 不同来源的样品 ID 不跨来源合并；1°格网只表示有实测点，不表示连续覆盖。",
            "- MarChem 外层 ZIP 漂移但数据表和方法表 hash 一致；该边界在自动化健康文件中单列。",
            "",
            "机器可读结果位于 `assets/v4-full-profiles/` 和 `assets/v4-coverage-cube.csv`。",
        ]
    )
    return "\n".join(lines) + "\n"


def expected_outputs() -> dict[Path, str]:
    outputs, spatial = _spatial_outputs()
    cube_text, cube_rows, already_canonical = _cube_output()
    balance_text, balance = _balance_output(spatial, already_canonical=already_canonical)
    outputs[CUBE_PATH] = cube_text
    outputs[BALANCE_PATH] = balance_text

    manifest = _load_json(MANIFEST_PATH)
    manifest["reported_coordinate_sample_count"] = sum(
        int(item["reported_coordinate_sample_count"]) for item in spatial.values()
    )
    manifest["valid_coordinate_sample_count"] = sum(
        int(item["valid_coordinate_sample_count"]) for item in spatial.values()
    )
    manifest["comparable_observation_count"] = sum(
        int(row["comparable_observation_count"]) for row in cube_rows
    )
    manifest["covered_spatial_cells_source_sum"] = sum(
        int(item["covered_spatial_cells"]) for item in spatial.values()
    )
    manifest["media"] = balance["media"]
    source_rows = {item["source_id"]: item for item in manifest["sources"]}
    for source_id, item in spatial.items():
        source = source_rows[source_id]
        source["reported_coordinate_sample_count"] = item["reported_coordinate_sample_count"]
        source["valid_coordinate_sample_count"] = item["valid_coordinate_sample_count"]
        source["covered_spatial_cells"] = item["covered_spatial_cells"]
        source["comparable_observation_count"] = sum(
            int(row["comparable_observation_count"])
            for row in cube_rows
            if row["source_id"] == source_id
        )
    report = _report(manifest)
    outputs[REPORT_PATH] = report
    artifact_paths = [SKILL_DIR / item["path"] for item in manifest["artifacts"]]
    manifest["artifacts"] = []
    for path in artifact_paths:
        content = outputs.get(path)
        if content is None:
            content = path.read_text(encoding="utf-8")
        manifest["artifacts"].append(
            {
                "path": str(path.relative_to(SKILL_DIR)),
                "bytes": len(content.encode("utf-8")),
                "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            }
        )
    outputs[MANIFEST_PATH] = _json_text(manifest)
    return outputs


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        outputs = expected_outputs()
        for path, content in outputs.items():
            if args.check:
                if not path.is_file() or path.read_text(encoding="utf-8") != content:
                    raise ReconciliationError(f"stale coordinate claim artifact: {path}")
            else:
                _atomic_text(path, content)
    except (OSError, ValueError, KeyError, json.JSONDecodeError, ReconciliationError) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps({"status": "PASS", "artifact_count": len(outputs)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
