#!/usr/bin/env python3
"""Build a deterministic D1/D2 follow-up backlog without imputing scientific evidence."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import tempfile
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "geochemistry-iteration-backlog-v2"
FIELDS = (
    "item_id",
    "record_id",
    "source_id",
    "stage_owner",
    "severity",
    "status",
    "issue_code",
    "field",
    "observed_value",
    "detail",
    "recommended_action",
    "auto_recheck",
)


def text(row: Mapping[str, str], field: str) -> str:
    return (row.get(field) or "").strip()


def truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "y"}


def finite_number(value: str) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def json_value(value: str, expected: type) -> Any:
    try:
        parsed = json.loads(value or "null")
    except json.JSONDecodeError:
        return expected()
    return parsed if isinstance(parsed, expected) else expected()


def item_id(record_id: str, issue_code: str, field: str, observed: str = "") -> str:
    normalized_observed = " ".join(str(observed).split())
    digest = hashlib.sha256(
        f"{record_id}\0{issue_code}\0{field}\0{normalized_observed}".encode()
    ).hexdigest()[:16]
    return f"ITER-{digest}"


def issue(
    row: Mapping[str, str],
    *,
    owner: str,
    severity: str,
    status: str,
    code: str,
    field: str,
    detail: str,
    action: str,
    observed: str = "",
    auto_recheck: bool = True,
) -> dict[str, str]:
    record_id = text(row, "record_id") or text(row, "source_record_id") or "unknown-record"
    return {
        "item_id": item_id(record_id, code, field, observed),
        "record_id": record_id,
        "source_id": text(row, "source_id") or "unknown",
        "stage_owner": owner,
        "severity": severity,
        "status": status,
        "issue_code": code,
        "field": field,
        "observed_value": observed,
        "detail": detail,
        "recommended_action": action,
        "auto_recheck": "true" if auto_recheck else "false",
    }


def issues_for_row(row: Mapping[str, str]) -> list[dict[str, str]]:
    found: list[dict[str, str]] = []
    if not text(row, "source_locator"):
        found.append(issue(row, owner="D1", severity="error", status="action_required",
            code="SOURCE_LOCATOR_MISSING", field="source_locator",
            detail="记录缺少可直接定位的来源证据。",
            action="回到公开数据页、文件或文献表格，补充稳定 URL/DOI/页码/表号；不要用数据集首页冒充记录定位。"))
    if not text(row, "license"):
        found.append(issue(row, owner="D1", severity="warning", status="action_required",
            code="LICENSE_MISSING", field="license", detail="复用许可未声明。",
            action="核对来源条款并记录许可、许可 URL 与适用范围；未确认前不得声称可再分发。"))
    latitude, longitude = finite_number(text(row, "latitude")), finite_number(text(row, "longitude"))
    if latitude is None or longitude is None or not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        found.append(issue(row, owner="D1", severity="error", status="action_required",
            code="COORDINATE_UNUSABLE", field="latitude,longitude",
            detail="WGS84 坐标缺失、非数值或超出合法范围，因此不能上图。",
            action="从原始来源恢复坐标与 CRS；若只提供区域名称，保留缺失并记录原因，不得填区域质心。",
            observed=f"{text(row, 'latitude')},{text(row, 'longitude')}"))
    sample_type = text(row, "sample_type")
    mapping_status = text(row, "sample_type_mapping_status")
    if not sample_type:
        found.append(issue(row, owner="D1", severity="warning", status="action_required",
            code="SAMPLE_TYPE_MISSING", field="sample_type",
            detail="细分样品类型未提供；medium 不能替代全部样品制备与环境语义。",
            action="从源字段提取原始样品类型，并按受控词表映射；保留 sample_type_raw 和映射状态。"))
    elif mapping_status and mapping_status not in {
        "mapped", "source_reported", "exact", "dataset_constant", "controlled_vocabulary"
    }:
        found.append(issue(row, owner="D2", severity="warning", status="review_required",
            code="SAMPLE_TYPE_MAPPING_REVIEW", field="sample_type_mapping_status",
            detail="样品类型映射不是明确的精确/来源直报状态。",
            action="复核映射表和原始术语；无法确定时保持 unknown，不做推测。", observed=mapping_status))
    analytical_method = text(row, "analytical_method")
    if not analytical_method or analytical_method.lower() in {"unknown", "not provided", "未提供"}:
        found.append(issue(row, owner="D1", severity="warning", status="action_required",
            code="ANALYTICAL_METHOD_MISSING", field="analytical_method",
            detail="分析方法证据缺失，跨来源浓度与元素组合不可可靠比较。",
            action="回查数据字典、方法论文或记录级元数据；同时绑定 method_source_locator，未找到时保留缺失原因。"))
    elif not text(row, "method_scope"):
        found.append(issue(row, owner="D2", severity="warning", status="action_required",
            code="METHOD_SCOPE_MISSING", field="method_scope",
            detail="已有方法名称，但尚未声明方法适用范围。",
            action="依据来源证据标注 record/dataset/publication 等范围；不得把数据集级方法伪装为记录级方法。"))
    if not text(row, "matched_geologic_unit") and not text(row, "geologic_unit"):
        found.append(issue(row, owner="D2", severity="info", status="review_required",
            code="GEOLOGIC_CONTEXT_MISSING", field="matched_geologic_unit",
            detail="记录没有来源直报或空间匹配的地质单元。",
            action="在比例尺与边界不确定性允许时执行空间匹配，并记录地图源、版本、匹配方法和边界距离；否则保留缺失。"))
    censored = truthy(text(row, "censored")) or text(row, "value_qualifier") in {"<", ">", "<=", ">="}
    if censored:
        found.append(issue(row, owner="D2", severity="info", status="scientific_limit",
            code="CENSORED_OBSERVATION", field="censored",
            detail="这是检出限/定量限约束的删失观测，不等同于零，也不自动视为采集失败。",
            action="保留原始 qualifier 与 censoring limit；默认从普通相关和异常筛查中排除，或使用明确的删失统计模型。",
            observed=text(row, "source_qualifier_raw") or text(row, "value_qualifier"), auto_recheck=False))
    normalized = finite_number(text(row, "normalized_value"))
    if normalized is None and not censored:
        found.append(issue(row, owner="D2", severity="error", status="action_required",
            code="NORMALIZATION_FAILED", field="normalized_value",
            detail="非删失测定没有可用标准值。",
            action="检查原值解析、单位词表、物质基准和换算公式；不能证明可换算时保留失败状态，不得猜值。"))
    if normalized is not None and not text(row, "normalized_unit"):
        found.append(issue(row, owner="D2", severity="error", status="action_required",
            code="NORMALIZED_UNIT_MISSING", field="normalized_unit",
            detail="标准值存在但标准单位缺失。",
            action="依据有证据的单位换算恢复标准单位；若来源单位不明，撤销伪标准化值。"))
    confidence = json_value(text(row, "operational_confidence"), dict)
    overall = confidence.get("overall")
    if isinstance(overall, (int, float)) and not isinstance(overall, bool) and overall < 0.5:
        found.append(issue(row, owner="D2", severity="warning", status="review_required",
            code="LOW_OPERATIONAL_CONFIDENCE", field="operational_confidence",
            detail="工作流可用性评分低于 0.5；该分数不是正确概率。",
            action="按 source/completeness/method/spatial/qc 分量定位短板，优先修复可追溯证据与错误级 QC。",
            observed=f"{overall:.6g}"))
    flags = json_value(text(row, "qc_flags"), list)
    for flag in sorted({str(value) for value in flags if value}):
        if flag.lower().startswith(("error", "invalid", "unsupported")):
            found.append(issue(row, owner="D2", severity="error", status="action_required",
                code="QC_ERROR_REVIEW", field="qc_flags", detail=f"记录含错误级或不可支持的 QC 标志：{flag}",
                action="按 QC 规则修复源字段或映射；修复前保持排除，不要删除原始记录。", observed=flag))
    return found


def build(database: Path, output: Path) -> dict[str, Any]:
    with database.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    items = [entry for row in rows for entry in issues_for_row(row)]
    items.sort(
        key=lambda value: (
            value["record_id"], value["issue_code"], value["field"],
            value["observed_value"], value["item_id"],
        )
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="", dir=output.parent, delete=False) as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(items)
        temporary = Path(handle.name)
    os.replace(temporary, output)
    return {
        "schema_version": SCHEMA_VERSION,
        "input_database_sha256": hashlib.sha256(database.read_bytes()).hexdigest(),
        "output_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "record_count": len(rows),
        "item_count": len(items),
        "status_counts": dict(sorted(Counter(item["status"] for item in items).items())),
        "owner_counts": dict(sorted(Counter(item["stage_owner"] for item in items).items())),
        "issue_counts": dict(sorted(Counter(item["issue_code"] for item in items).items())),
    }


def load(path: Path, preview_limit: int = 500) -> dict[str, Any]:
    if not path.is_file():
        return {"schema_version": SCHEMA_VERSION, "item_count": 0, "status_counts": {}, "owner_counts": {}, "issue_counts": {}, "preview": []}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        items = list(csv.DictReader(handle))
    return {
        "schema_version": SCHEMA_VERSION,
        "item_count": len(items),
        "status_counts": dict(sorted(Counter(item.get("status", "") for item in items).items())),
        "owner_counts": dict(sorted(Counter(item.get("stage_owner", "") for item in items).items())),
        "issue_counts": dict(sorted(Counter(item.get("issue_code", "") for item in items).items())),
        "preview": items[:preview_limit],
        "preview_truncated": len(items) > preview_limit,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a D1/D2 evidence and processing iteration backlog.")
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    print(json.dumps(build(args.database, args.output), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
