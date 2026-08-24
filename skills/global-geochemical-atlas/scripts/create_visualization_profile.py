#!/usr/bin/env python3
"""Create a validated D3 task profile from explicit question parameters."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import build_interactive_map as map_builder
import spatial_scope


STORIES = ("overview", "coverage", "anomaly", "comparison", "database", "evidence")
STORY_LABELS = {
    "overview": "分布总览",
    "coverage": "覆盖与密度",
    "anomaly": "富集与亏损候选",
    "comparison": "元素组合",
    "database": "标准化数据库",
    "evidence": "置信度与来源",
}


def optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def default_display(story: str, spatial_scope: str) -> dict[str, Any]:
    if story == "coverage":
        map_mode = "heat"
        anomaly_regions = False
    elif story == "anomaly":
        map_mode = "distribution"
        anomaly_regions = True
    else:
        map_mode = "combined"
        anomaly_regions = True
    return {
        "map_mode": map_mode,
        "color_by": "value",
        "anomaly_grid_degrees": 1 if spatial_scope == "regional" else 2,
        "show_anomaly_points": False,
        "show_anomaly_regions": anomaly_regions,
    }


def build_profile(args: argparse.Namespace) -> dict[str, Any]:
    region = args.region or ("global" if args.spatial_scope == "global" else None)
    if region is None:
        raise ValueError("--spatial-scope regional requires --region")
    if args.spatial_scope == "global" and region != "global":
        raise ValueError("--spatial-scope global requires --region global")
    if args.spatial_scope == "regional" and region == "global":
        raise ValueError("--spatial-scope regional requires a non-global --region")
    if region == "custom":
        if args.bbox is None or optional_text(args.region_label) is None:
            raise ValueError(
                "--region custom requires --bbox W S E N and --region-label"
            )
        w, s, e, n = args.bbox
        custom_region: dict[str, Any] | None = {
            "label": args.region_label.strip(),
            "bounds": {"w": w, "s": s, "e": e, "n": n},
            "country_code": None,
        }
        region_label = args.region_label.strip()
    elif region in map_builder.REGION_PRESETS:
        if args.bbox is not None or args.region_label is not None:
            raise ValueError(
                "--bbox and --region-label are only valid with --region custom"
            )
        custom_region = None
        region_label = str(map_builder.REGION_PRESETS[region]["label"])
    else:
        if args.bbox is not None or args.region_label is not None:
            raise ValueError(
                "--bbox and --region-label are only valid with --region custom"
            )
        try:
            resolved = spatial_scope.resolve_region(region)
        except spatial_scope.SpatialScopeError as exc:
            raise ValueError(str(exc)) from exc
        if resolved["key"] == "global":
            region = "global"
            custom_region = None
        else:
            west, south, east, north = resolved["bbox"]
            region = "custom"
            custom_region = {
                "label": resolved["label"],
                "bounds": {"w": west, "s": south, "e": east, "n": north},
                "country_code": resolved.get("country_code"),
            }
        region_label = str(resolved["label"])

    comparison_values = (
        optional_text(args.comparison_x),
        optional_text(args.comparison_y),
    )
    if (comparison_values[0] is None) != (comparison_values[1] is None):
        raise ValueError("--comparison-x and --comparison-y must be supplied together")
    if args.story == "comparison" and None in comparison_values:
        raise ValueError("story=comparison requires --comparison-x and --comparison-y")
    if (
        comparison_values[0] is not None
        and comparison_values[0] == comparison_values[1]
    ):
        raise ValueError("comparison elements must be different")

    filters = {
        "element": optional_text(args.element),
        "medium": optional_text(args.medium),
        "sample_type": optional_text(args.sample_type),
        "basis": optional_text(args.basis),
        "geology": optional_text(args.geology),
        "method": optional_text(args.method),
        "method_scope": optional_text(args.method_scope),
        "source": optional_text(args.source),
        "confidence": optional_text(args.confidence),
    }
    display = default_display(args.story, args.spatial_scope)
    if args.map_mode is not None:
        display["map_mode"] = args.map_mode
    if args.color_by is not None:
        display["color_by"] = args.color_by
    if args.anomaly_grid is not None:
        display["anomaly_grid_degrees"] = args.anomaly_grid
    if args.show_anomaly_points:
        display["show_anomaly_points"] = True
    if args.hide_anomaly_regions:
        display["show_anomaly_regions"] = False

    filter_summary = [
        f"{key}={value}" for key, value in filters.items() if value is not None
    ]
    if comparison_values[0] is not None:
        filter_summary.append(f"组合={comparison_values[0]}×{comparison_values[1]}")
    scope_summary = "全球" if args.spatial_scope == "global" else region_label
    title = optional_text(args.title) or f"{scope_summary}地球化学元素图谱"
    subtitle = optional_text(args.subtitle) or (
        f"{scope_summary}范围的标准化地球化学观测"
        + ("；筛选：" + "，".join(filter_summary) if filter_summary else "")
        + "。空白区域表示当前数据未覆盖。"
    )
    return {
        "schema_version": map_builder.PROFILE_VERSION,
        "title": title,
        "subtitle": subtitle,
        "story": args.story,
        "theme": "evidence-dark",
        "spatial_scope": args.spatial_scope,
        "default_region": region,
        "custom_region": custom_region,
        "filters": filters,
        "comparison": {
            "x": comparison_values[0],
            "y": comparison_values[1],
            "medium": optional_text(args.comparison_medium),
        },
        "display": display,
    }


def validate_profile(profile: dict[str, Any], parent: Path) -> dict[str, Any]:
    parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=parent, suffix=".json", delete=False
    ) as handle:
        json.dump(profile, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    try:
        return map_builder.load_visualization_profile(temporary)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Create a validated d3-visualization-profile-v2 without editing the HTML template. "
            "The calling Agent must translate the user question into explicit parameters."
        )
    )
    parser.add_argument(
        "--output", required=True, type=Path, help="Profile JSON to create"
    )
    parser.add_argument("--story", choices=STORIES, default="overview")
    parser.add_argument(
        "--spatial-scope", choices=("global", "regional"), default="global"
    )
    parser.add_argument(
        "--region",
        help="global, a bundled preset, a Natural Earth country name/ISO-3, or custom",
    )
    parser.add_argument("--bbox", nargs=4, type=float, metavar=("W", "S", "E", "N"))
    parser.add_argument("--region-label")
    parser.add_argument("--element")
    parser.add_argument("--medium")
    parser.add_argument("--sample-type")
    parser.add_argument("--basis")
    parser.add_argument("--geology")
    parser.add_argument("--method")
    parser.add_argument("--method-scope")
    parser.add_argument("--source")
    parser.add_argument("--confidence")
    parser.add_argument("--comparison-x")
    parser.add_argument("--comparison-y")
    parser.add_argument("--comparison-medium")
    parser.add_argument("--map-mode", choices=("distribution", "heat", "combined"))
    parser.add_argument("--color-by", choices=("medium", "element", "value"))
    parser.add_argument("--anomaly-grid", type=int, choices=(1, 2, 5))
    parser.add_argument("--show-anomaly-points", action="store_true")
    parser.add_argument("--hide-anomaly-regions", action="store_true")
    parser.add_argument("--title")
    parser.add_argument("--subtitle")
    parser.add_argument(
        "--force", action="store_true", help="Replace an existing profile"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.output.exists() and not args.force:
        parser.error(
            f"output already exists; choose a new path or pass --force: {args.output}"
        )
    try:
        profile = validate_profile(build_profile(args), args.output.parent)
    except (ValueError, map_builder.MapBuildError) as exc:
        parser.error(str(exc))
    atomic_json(args.output, profile)
    print(
        json.dumps(
            {
                "status": "success",
                "output": str(args.output),
                "story": profile["story"],
                "spatial_scope": profile["spatial_scope"],
                "region": profile["default_region"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
