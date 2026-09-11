"""Screening-level provenance classification for enrichment anomalies.

Contract ``anomaly-provenance-v1``.

What this answers, in plain terms: for every high-side anomaly candidate,
is the enrichment more likely inherited from the parent material of the
soil/sediment/rock (geogenic), or more likely added later by industrial
emissions or other human input (anthropogenic)?  The classifier weighs
four independent evidence lines and refuses to guess when they are thin:

1. lithology  -- is the sample sitting on rock types known to carry high
   natural backgrounds of this element (ultramafic rocks for Ni/Cr/Co,
   black shales for As/Mo, ...)?
2. spatial    -- do nearby samples of the same element and medium also
   flag high (broad geologic patterns are spatially coherent, while
   point-source pollution tends to stand alone)?
3. association -- do other elements on the same physical sample flag
   high together (chalcophile suites such as Pb-Zn-Cd-Cu rising together
   are a classic pollution fingerprint; a lone mafic-suite element
   points at the parent rock instead)?
4. temporal   -- where the same station carries three or more dated
   observations (sampling_time from the atlas-sampling-time-v1 contract),
   does the concentration rise over the observed period?  Rising series
   support later input; flat series support a stable natural background.

Every verdict lists which lines were available and what each one said.
A candidate with fewer than two usable lines, or with single-line
support only, stays ``insufficient_evidence`` -- the honest default.
Low-side (depletion) candidates are reported but not attributed; this
contract only covers enrichment.  No verdict ever names a specific
polluter or claims causality; that would need isotope ratios or emission
inventories which the registered sources do not carry.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

CONTRACT_ID = "anomaly-provenance-v1"

CLASS_GEOGENIC = "geogenic_background"
CLASS_ANTHROPOGENIC = "suspected_anthropogenic_input"
CLASS_MIXED = "mixed_or_undistinguished"
CLASS_INSUFFICIENT = "insufficient_evidence"
CLASS_DEPLETION = "not_applicable_depletion"

CLASS_LABELS_ZH = {
    CLASS_GEOGENIC: "母质高背景型（地质成因）",
    CLASS_ANTHROPOGENIC: "疑似人为输入型",
    CLASS_MIXED: "混合叠加型",
    CLASS_INSUFFICIENT: "证据不足，暂不判定",
    CLASS_DEPLETION: "亏损候选（本版不做成因归因）",
}

# Rock families with well-documented naturally high backgrounds, matched
# as case-insensitive substrings against lithology_raw / geologic_unit.
HIGH_BACKGROUND_LITHOLOGY: tuple[tuple[tuple[str, ...], frozenset[str]], ...] = (
    (
        ("ULTRAMAFIC", "PERIDOTITE", "SERPENTIN", "DUNITE", "PYROXENITE", "KOMATIITE"),
        frozenset({"Ni", "Cr", "Co"}),
    ),
    (
        ("BASALT", "GABBRO", "DOLERITE", "DIABASE", "AMPHIBOLITE", "GREENSTONE"),
        frozenset({"Ni", "Cr", "Cu", "Co", "V"}),
    ),
    (
        ("BLACK SHALE", "SHALE", "SCHIST"),
        frozenset({"As", "Mo", "U", "V", "Zn"}),
    ),
)

# Chalcophile suite rising together is a classic pollution fingerprint.
CHALCOPHILE_SUITE = frozenset({"Pb", "Zn", "Cd", "Cu", "Hg", "As", "Sb"})
# Mafic suite points at the parent rock.
MAFIC_SUITE = frozenset({"Ni", "Cr", "Co", "V"})

SPATIAL_NEIGHBOR_DEGREES = 1.0
MIN_TEMPORAL_OBSERVATIONS = 3
TEMPORAL_RELATIVE_CHANGE = 0.30

SUPPORTS_GEOGENIC = "supports_geogenic"
SUPPORTS_ANTHROPOGENIC = "supports_anthropogenic"
NEUTRAL = "available_but_neutral"
UNAVAILABLE = "unavailable"


class ProvenanceError(RuntimeError):
    pass


def _float(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def _sampling_year(value: str) -> float | None:
    """Numeric year for trend fitting; year ranges use their midpoint."""
    text = value.strip()
    if not text:
        return None
    if "/" in text:
        parts = text.split("/")
        try:
            return (int(parts[0]) + int(parts[1])) / 2.0
        except ValueError:
            return None
    try:
        year = float(text[:4])
    except ValueError:
        return None
    if len(text) >= 7 and text[4] == "-":
        try:
            year += (int(text[5:7]) - 1) / 12.0
        except ValueError:
            pass
    return year


def _station_key(row: dict[str, str]) -> tuple[Any, ...] | None:
    sample_id = str(row.get("sample_id") or "")
    if row.get("source_id") == "gemstat-open-archive" and "|" in sample_id:
        return ("station", row["source_id"], sample_id.split("|", 1)[0])
    latitude = _float(row.get("latitude"))
    longitude = _float(row.get("longitude"))
    if latitude is None or longitude is None:
        return None
    return ("cell", row.get("source_id"), round(latitude, 2), round(longitude, 2))


def _lithology_line(record: dict[str, str], element: str) -> tuple[str, str]:
    text = " ".join(
        str(record.get(field) or "")
        for field in ("lithology", "lithology_raw", "geologic_unit")
    ).upper()
    if not text.strip():
        return UNAVAILABLE, "样本未附岩性/地质单元信息，这条证据线用不上。"
    for keywords, elements in HIGH_BACKGROUND_LITHOLOGY:
        if element in elements and any(keyword in text for keyword in keywords):
            return (
                SUPPORTS_GEOGENIC,
                f"样本岩性属于 {element} 天然高背景岩类，母质本身就富含该元素。",
            )
    return (
        NEUTRAL,
        "样本附有岩性信息，但不属于该元素的已知天然高背景岩类。",
    )


def _spatial_line(
    feature: dict[str, Any],
    peers: list[tuple[float, float]],
    total_high_candidates: int,
) -> tuple[str, str]:
    latitude = _float(feature.get("latitude"))
    longitude = _float(feature.get("longitude"))
    if latitude is None or longitude is None:
        return UNAVAILABLE, "该点缺少规范坐标，无法检查空间连片性。"
    neighbors = sum(
        1
        for peer_lat, peer_lon in peers
        if abs(peer_lat - latitude) <= SPATIAL_NEIGHBOR_DEGREES
        and abs(peer_lon - longitude) <= SPATIAL_NEIGHBOR_DEGREES
    )
    if neighbors >= 2:
        return (
            SUPPORTS_GEOGENIC,
            f"约 1 度范围内还有 {neighbors} 个同元素同介质的偏高点，"
            "空间上成片，更像地质格局。",
        )
    if neighbors == 0 and total_high_candidates >= 3:
        return (
            SUPPORTS_ANTHROPOGENIC,
            "同元素同介质的其它偏高点都离得很远，这个点是孤立热点，更像点源输入。",
        )
    return NEUTRAL, "邻域内偏高点数量介于两可之间，空间证据不倾向任何一方。"


def _association_line(
    element: str,
    sample_elements: set[str],
    sample_high_flags: set[str],
) -> tuple[str, str]:
    others_measured = sample_elements - {element}
    if not others_measured:
        return UNAVAILABLE, "同一样本没有其它元素的测量，伴生证据线用不上。"
    co_high = sample_high_flags - {element}
    chalcophile_together = ({element} | co_high) & CHALCOPHILE_SUITE
    if element in CHALCOPHILE_SUITE and len(chalcophile_together) >= 2 and co_high:
        return (
            SUPPORTS_ANTHROPOGENIC,
            "同一样本上 "
            + "、".join(sorted(chalcophile_together))
            + " 等亲硫元素一起偏高，是典型的污染组合指纹。",
        )
    if element in (MAFIC_SUITE | {"Cu"}) and co_high & MAFIC_SUITE:
        return (
            SUPPORTS_GEOGENIC,
            "同一样本上伴随偏高的是 "
            + "、".join(sorted(co_high & MAFIC_SUITE))
            + " 这类基性岩指示元素，指向母质本身。",
        )
    if not co_high:
        return (
            NEUTRAL,
            "同一样本测了其它元素但只有这一个偏高，伴生证据不构成组合指纹。",
        )
    return NEUTRAL, "伴生偏高元素的组合不构成明确的污染或母质指纹。"


def _temporal_line(series: list[tuple[float, float]]) -> tuple[str, str]:
    if len(series) < MIN_TEMPORAL_OBSERVATIONS:
        return (
            UNAVAILABLE,
            "该点位带采样时间的观测少于 3 次，看不出时间趋势。",
        )
    ordered = sorted(series)
    years = [item[0] for item in ordered]
    values = [item[1] for item in ordered]
    mean_year = sum(years) / len(years)
    mean_value = sum(values) / len(values)
    denominator = sum((year - mean_year) ** 2 for year in years)
    if denominator == 0:
        return UNAVAILABLE, "观测时间过于集中，无法拟合趋势。"
    slope = (
        sum((y - mean_year) * (v - mean_value) for y, v in zip(years, values))
        / denominator
    )
    median_value = sorted(values)[len(values) // 2]
    if median_value <= 0:
        return UNAVAILABLE, "浓度序列包含非正值，趋势幅度无法归一。"
    relative_change = slope * (years[-1] - years[0]) / median_value
    span = f"{years[0]:.0f}-{years[-1]:.0f} 年"
    if relative_change > TEMPORAL_RELATIVE_CHANGE:
        return (
            SUPPORTS_ANTHROPOGENIC,
            f"该点位 {span} 的 {len(series)} 次观测浓度明显上升"
            f"（相对变幅约 {relative_change:+.0%}），符合后天持续输入的特征；"
            "仅描述观测序列，不外推。",
        )
    if relative_change < -TEMPORAL_RELATIVE_CHANGE:
        return (
            NEUTRAL,
            f"该点位 {span} 的观测浓度在下降（约 {relative_change:+.0%}），"
            "可能与治理或输入减少有关，但不指向母质成因；仅描述观测序列。",
        )
    return (
        SUPPORTS_GEOGENIC,
        f"该点位 {span} 的 {len(series)} 次观测浓度基本平稳"
        f"（相对变幅约 {relative_change:+.0%}），符合稳定天然背景的特征。",
    )


def _classify(lines: dict[str, tuple[str, str]]) -> tuple[str, str]:
    verdicts = [verdict for verdict, _ in lines.values()]
    available = sum(1 for verdict in verdicts if verdict != UNAVAILABLE)
    geogenic = sum(1 for verdict in verdicts if verdict == SUPPORTS_GEOGENIC)
    anthropogenic = sum(1 for verdict in verdicts if verdict == SUPPORTS_ANTHROPOGENIC)
    if geogenic >= 1 and anthropogenic >= 1:
        return (
            CLASS_MIXED,
            "不同证据线各指向一边：既有地质背景的信号，也有人为输入的信号，"
            "这里的富集很可能是母质背景叠加了后天输入。",
        )
    if available >= 2 and geogenic >= 2:
        return (
            CLASS_GEOGENIC,
            "多条证据线一致指向母质：这里的富集更可能是土壤或其他介质的母质"
            "先天决定的天然高背景，按通用标准直接判超标会造成假异常。",
        )
    if available >= 2 and anthropogenic >= 2:
        return (
            CLASS_ANTHROPOGENIC,
            "多条证据线一致指向后天输入：这里的富集更可能来自工业排放或其他"
            "人为原因，而不是母质本身，建议按污染线索跟进。",
        )
    return (
        CLASS_INSUFFICIENT,
        "可用的证据线不足两条同向支持，按本契约保持不判定，"
        "等补充岩性、时序或伴生元素数据后再归因。",
    )


def build(database_path: Path, anomalies_path: Path) -> dict[str, Any]:
    try:
        with database_path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except OSError as exc:
        raise ProvenanceError(f"unreadable database: {database_path}") from exc
    try:
        anomalies = json.loads(anomalies_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProvenanceError(f"unreadable anomalies: {anomalies_path}") from exc

    by_record_id = {str(row.get("record_id") or ""): row for row in rows}
    sample_elements: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        sample_id = str(row.get("sample_id") or "").strip()
        element = str(row.get("element_or_analyte") or "").strip()
        if sample_id and element:
            sample_elements[sample_id].add(element)

    station_series: dict[tuple[Any, ...], list[tuple[float, float]]] = defaultdict(list)
    for row in rows:
        if str(row.get("sampling_time_status") or "") != "publisher_reported":
            continue
        year = _sampling_year(str(row.get("sampling_time") or ""))
        value = _float(row.get("normalized_value")) or _float(row.get("value"))
        station = _station_key(row)
        element = str(row.get("element_or_analyte") or "").strip()
        if year is None or value is None or station is None or not element:
            continue
        station_series[station + (element,)].append((year, value))

    features = anomalies.get("features") or []
    high_positions: dict[tuple[str, str], list[tuple[float, float]]] = defaultdict(list)
    high_flags_by_sample: dict[str, set[str]] = defaultdict(set)
    prepared: list[dict[str, Any]] = []
    for feature in features:
        properties = feature.get("properties") or {}
        geometry = feature.get("geometry") or {}
        coordinates = geometry.get("coordinates") or [None, None]
        record = by_record_id.get(str(properties.get("record_id") or ""), {})
        item = {
            "record_id": str(properties.get("record_id") or ""),
            "element": str(properties.get("element_or_analyte") or ""),
            "medium": str(properties.get("medium") or ""),
            "direction": str(properties.get("direction") or ""),
            "latitude": coordinates[1],
            "longitude": coordinates[0],
            "record": record,
        }
        prepared.append(item)
        if item["direction"] == "high":
            sample_id = str(record.get("sample_id") or "").strip()
            if sample_id:
                high_flags_by_sample[sample_id].add(item["element"])
            latitude = _float(item["latitude"])
            longitude = _float(item["longitude"])
            if latitude is not None and longitude is not None:
                high_positions[(item["element"], item["medium"])].append(
                    (latitude, longitude)
                )

    results: list[dict[str, Any]] = []
    counts: dict[str, int] = {label: 0 for label in CLASS_LABELS_ZH}
    for item in sorted(prepared, key=lambda entry: entry["record_id"]):
        record = item["record"]
        element = item["element"]
        if item["direction"] != "high":
            classification = CLASS_DEPLETION
            plain = (
                "这是相对背景偏低（亏损）的候选，本契约的成因归因只覆盖富集，"
                "该点保留为筛查线索。"
            )
            lines_out: dict[str, dict[str, str]] = {}
        else:
            latitude = _float(item["latitude"])
            longitude = _float(item["longitude"])
            peers = [
                position
                for position in high_positions[(element, item["medium"])]
                if latitude is None
                or longitude is None
                or position != (latitude, longitude)
            ]
            sample_id = str(record.get("sample_id") or "").strip()
            station = _station_key(record) if record else None
            series = (
                station_series.get(station + (element,), [])
                if station is not None
                else []
            )
            lines = {
                "lithology": _lithology_line(record, element),
                "spatial": _spatial_line(
                    item, peers, len(high_positions[(element, item["medium"])])
                ),
                "association": _association_line(
                    element,
                    sample_elements.get(sample_id, set()),
                    high_flags_by_sample.get(sample_id, set()),
                ),
                "temporal": _temporal_line(series),
            }
            classification, plain = _classify(lines)
            lines_out = {
                name: {"verdict": verdict, "plain_language": explanation}
                for name, (verdict, explanation) in lines.items()
            }
        counts[classification] += 1
        results.append(
            {
                "record_id": item["record_id"],
                "element": element,
                "medium": item["medium"],
                "direction": item["direction"],
                "classification": classification,
                "classification_label_zh": CLASS_LABELS_ZH[classification],
                "plain_language": plain,
                "evidence_lines": lines_out,
            }
        )

    return {
        "contract": CONTRACT_ID,
        "interpretation": (
            "异常区域识别在“相对背景偏高/偏低”的基础上增加了成因归因：结合时序"
            "信息等证据，分析元素富集究竟是土壤或其他介质的母质先天决定的，还是"
            "工业排放或其他人为原因导致的。归因是筛查级的，不指认具体污染源，"
            "也不替代法规判定。"
        ),
        "evidence_line_definitions": {
            "lithology": "岩性线：样本是否落在该元素天然高背景的岩类上。",
            "spatial": "空间线：同元素同介质的偏高点是否在邻域内成片（地质格局）"
            "还是孤立（点源特征）。",
            "association": "伴生线：同一样本上其它元素是否组合性偏高"
            "（亲硫组合像污染指纹，基性岩组合像母质信号）。",
            "temporal": "时序线：同一点位多次带采样时间的观测，浓度上升支持后天"
            "输入，平稳支持稳定背景。",
        },
        "classification_labels_zh": dict(CLASS_LABELS_ZH),
        "classification_counts": {
            key: counts[key] for key in sorted(counts) if counts[key]
        },
        "candidate_count": len(results),
        "anomalies": results,
        "caveat": (
            "筛查级归因，非因果结论。判定只使用已注册来源内的证据；缺证据时"
            "保持“证据不足，暂不判定”，不借用发表年冒充采样时间，也不虚构"
            "污染源。"
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Classify enrichment anomaly candidates as geogenic background, "
            "suspected anthropogenic input, mixed, or insufficient evidence."
        )
    )
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--anomalies", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    report = build(args.database, args.anomalies)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "candidate_count": report["candidate_count"],
                "classification_counts": report["classification_counts"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
