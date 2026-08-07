#!/usr/bin/env python3
"""Build a conservative, reproducible coverage matrix from the D1 source catalog."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import source_adapters
import source_router

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
DEFAULT_CATALOG = SKILL_DIR / "assets" / "source_catalog.json"
DEFAULT_REQUEST = SKILL_DIR / "fixtures" / "source-routing" / "global-all-media-request.json"

COVERAGE_VERSION = "geochemical-coverage-matrix-v3"


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"{label} does not exist: {path}") from exc
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not valid UTF-8 JSON: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def build_matrix(
    catalog: Mapping[str, Any],
    request: Mapping[str, Any],
    registry: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Summarize route coverage while keeping unverified dimensions unknown."""

    resolved_registry = dict(registry) if registry is not None else source_adapters.load_source_registry()
    route = source_router.route_sources(request, catalog, resolved_registry)
    routed_sources = {
        item["source_id"]: item for item in [*route["selected_sources"], *route["review_sources"]]
    }
    cells: dict[str, Any] = {}
    for medium in route["request"]["media"]:
        routed = route["coverage"][medium]
        selected = routed["selected_sources"]
        candidates = routed["candidate_sources"]
        source_scopes = {
            source_id: catalog["sources"][source_id]["coverage"]["extent_class"]
            for source_id in [*selected, *candidates]
        }
        source_target_analytes = {
            source_id: sorted(resolved_registry["sources"][source_id].get("target_analytes", {}))
            for source_id in selected
            if source_id in resolved_registry.get("sources", {})
        }
        audited_analytes = sorted(
            {
                analyte
                for analytes in source_target_analytes.values()
                for analyte in analytes
            }
        )
        requested_analytes = list(route["request"]["elements"])
        analyte_source_counts = {
            analyte: sum(analyte in analytes for analytes in source_target_analytes.values())
            for analyte in requested_analytes
        }
        analytes_with_single_source = sorted(
            analyte for analyte, count in analyte_source_counts.items() if count == 1
        )
        analytes_with_multiple_sources = sorted(
            analyte for analyte, count in analyte_source_counts.items() if count > 1
        )
        lineage_ids = sorted({source_adapters.source_lineage_id(source_id) for source_id in selected})
        if len(selected) == 1:
            independence = "single_source_dependency"
        elif len(lineage_ids) == 1:
            independence = "multiple_datasets_single_upstream_lineage"
        elif len(selected) > 1 and analytes_with_single_source:
            independence = "multiple_sources_but_single_source_per_analyte"
        elif len(selected) > 1:
            independence = "multiple_independent_lineages"
        else:
            independence = "no_current_analysis_source"
        missing_analytes = sorted(set(requested_analytes) - set(audited_analytes))
        if not source_target_analytes:
            analyte_coverage = "unknown"
        elif not missing_analytes:
            analyte_coverage = "complete_for_registered_targets"
        elif set(audited_analytes).intersection(requested_analytes):
            analyte_coverage = "partial"
        else:
            analyte_coverage = "none"
        cells[medium] = {
            "status": routed["status"],
            "requested_analytes": requested_analytes,
            "analyte_coverage": analyte_coverage,
            "audited_analytes": audited_analytes,
            "missing_analytes": missing_analytes,
            "source_target_analytes": source_target_analytes,
            "analyte_source_counts": analyte_source_counts,
            "analytes_with_single_source": analytes_with_single_source,
            "analytes_with_multiple_sources": analytes_with_multiple_sources,
            "selected_sources": selected,
            "candidate_sources": candidates,
            "source_scopes": source_scopes,
            "source_evidence_tiers": {
                source_id: routed_sources[source_id]["evidence_tier"] for source_id in source_scopes
            },
            "source_use_modes": {
                source_id: routed_sources[source_id]["use_mode"] for source_id in source_scopes
            },
            "source_independence": independence,
            "independent_lineage_count": len(lineage_ids),
            "lineage_ids": lineage_ids,
            "method_metadata_coverage": "not_yet_audited",
            "spatial_density_coverage": "not_yet_audited",
            "temporal_coverage": "not_yet_audited",
            "note": routed["note"],
        }
    coverage_states = {cell["status"] for cell in cells.values()}
    if coverage_states == {"covered"}:
        overall = "covered"
    elif "partial" in coverage_states:
        overall = "partial"
    elif coverage_states == {"uncovered"}:
        overall = "uncovered"
    else:
        overall = "unknown"
    return {
        "coverage_version": COVERAGE_VERSION,
        "as_of": catalog["reviewed_at"],
        "overall_status": overall,
        "request": route["request"],
        "discovery": catalog["discovery_state"],
        "cells": cells,
        "route_status": route["status"],
        "limitations": [
            *route["limitations"],
            "Analyte coverage is credited only for explicit target mappings in the production registry; method, time and spatial-density coverage still require separate audits.",
            "Record count alone is not evidence of representative global coverage.",
        ],
        "claim_boundary": (
            "Coverage states describe sources that meet the requested evidence/use mode and documented lower-use candidates. "
            "They do not imply uniform sampling, method comparability, or absence of undiscovered sources."
        ),
    }


def render_markdown(matrix: Mapping[str, Any]) -> str:
    """Render the coverage matrix as an auditable human-readable report."""

    lines = [
        "# D1 数据源覆盖报告",
        "",
        f"核对时间：`{matrix['as_of']}`",
        "",
        f"整体状态：`{matrix['overall_status']}`",
        "",
        f"发现轮次：`{matrix['discovery']['round']}`，饱和状态：`{str(matrix['discovery']['saturated']).lower()}`",
        "",
        "## 当前目标",
        "",
        f"- 地区：`{json.dumps(matrix['request']['region'], ensure_ascii=False)}`",
        f"- 介质：`{', '.join(matrix['request']['media'])}`",
        f"- 分析物：`{', '.join(matrix['request']['elements'])}`",
        f"- 科研使用策略：`{matrix['request']['research_use_policy']}`",
        f"- 最低证据等级：`{matrix['request']['minimum_evidence_tier']}`",
        f"- 最低使用级别：`{matrix['request']['minimum_use_mode']}`",
        "",
        "## 覆盖矩阵",
        "",
        "| 介质 | 状态 | 当前分析来源 | 其他候选 | 来源独立性 | 分析物/方法/密度 |",
        "|---|---|---|---|---|---|",
    ]
    for medium, cell in matrix["cells"].items():
        selected = ", ".join(cell["selected_sources"]) or "无"
        candidates = ", ".join(cell["candidate_sources"]) or "无"
        unknowns = "/".join(
            (cell["analyte_coverage"], cell["method_metadata_coverage"], cell["spatial_density_coverage"])
        )
        lines.append(
            f"| {medium} | `{cell['status']}` | {selected} | {candidates} | "
            f"`{cell['source_independence']}` | `{unknowns}` |"
        )
    lines.extend(["", "## 当前判断", ""])
    for medium, cell in matrix["cells"].items():
        selected = "、".join(cell["selected_sources"]) or "无当前可执行来源"
        if cell["analyte_coverage"] == "none":
            analyte_note = f"请求元素均缺失：{', '.join(cell['missing_analytes'])}"
        elif cell["missing_analytes"]:
            analyte_note = f"缺失元素：{', '.join(cell['missing_analytes'])}"
        else:
            analyte_note = "注册目标覆盖本次元素；仍需记录级核验"
        lines.append(
            f"- `{medium}`：状态 `{cell['status']}`；来源 {selected}；{analyte_note}；"
            f"来源独立性 `{cell['source_independence']}`。"
        )
    lines.extend(
        [
            "- 岩石有 GEOROC 太古宙和南极洲两个数据集，但同属 GEOROC compilation 上游血缘，因此独立血缘仍为 1，整体仍是 `partial`；",
            "- 土壤已有 USGS、PANGAEA、AfSIS、FOREGS、TPDC 和 GEMAS 六条上游血缘；消解/浸取范围、土层和空间密度不同，仍为 `partial`；",
            "- 沉积物有七个数据集、六条上游血缘；海洋/河流/泛滥平原、粒级和消解基础不同，仍为 `partial`；",
            "- 水体有 GEOTRACES 海水、GEMStat 淡水、FOREGS 欧洲溪流水和 WQP 萨克拉门托河四条血缘；海水/淡水、分相、单位和时间尺度不可直接混为同一背景；",
            "- FOREGS 六类来源已分别实现适配器，但属于同一上游项目血缘；这增加了欧洲低密度基线覆盖，不代表欧洲每个位置有实测值；",
            "- AfSIS V2.0 已固定三个 original 文件并全量对账 2,002 个样品；126 个缺坐标样品和逐元素低于 DL/QL 的数值保持显式，不能用 48 条完整坐标 demo 代替全量质量结论；",
            "- 岩石、土壤和沉积物样板的 As、Cu、Ni、Zn 目标字段已登记；来源数增加不代表方法一致或空间充分，方法、时间和密度仍需逐源审计；",
            "- 方法、时间与空间密度没有完成记录级审计时保持 `not_yet_audited`；不得用来源数量替代覆盖结论。",
            "- 聚合平台不计作独立证据，必须追溯并去重其上游数据集。",
            "",
            "## 限制",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in matrix["limitations"])
    lines.extend(["", "## 结论边界", "", matrix["claim_boundary"]])
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--request", type=Path, default=DEFAULT_REQUEST)
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--markdown-output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        catalog = source_router.load_catalog(args.catalog)
        request = _read_json(args.request, "request")
        registry = source_adapters.load_source_registry()
        matrix = build_matrix(catalog, request, registry)
        rendered_json = json.dumps(matrix, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        rendered_markdown = render_markdown(matrix)
        if args.json_output:
            args.json_output.parent.mkdir(parents=True, exist_ok=True)
            args.json_output.write_text(rendered_json, encoding="utf-8")
        if args.markdown_output:
            args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
            args.markdown_output.write_text(rendered_markdown, encoding="utf-8")
        print(rendered_json, end="")
        return 0
    except (OSError, ValueError, source_adapters.SourceAdapterError) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
