#!/usr/bin/env python3
"""Deterministic discovery-topic proposer for the GGA research layer.

Consumes research_mode products (analysis_cohorts.csv, sampling_priority.geojson)
from one finished run and emits ranked, evidence-linked research-topic candidates
(discovery_candidates.json / .md). Stdlib only; no new data acquisition; every
candidate carries pointers into the run's own files.
"""

import argparse
import csv
import hashlib
import json
import os
from collections import defaultdict

USABLE = {"analysis_ready", "single_lineage_ready"}
PAIR_RULES = {
    "soil": (
        {
            "soil_topsoil",
            "soil_a_horizon",
            "soil_humus",
            "soil_organic_litter",
            "soil_surface",
        },
        {"soil_subsoil", "soil_c_horizon"},
    ),
    "sediment": (
        {"sediment_outlet_top", "sediment_marine_surface"},
        {"sediment_outlet_bottom", "sediment_marine_core"},
    ),
}
STAT_TEMPLATE = (
    "sites = coordinates rounded to 0.01 deg; per-site median within one "
    "method family; surface/deep ratio per site; report median ratio, "
    "bootstrap 95% CI, Wilcoxon signed-rank on log ratio; sensitivity: "
    "0.1 deg grid and alternative method family; geogenic controls (Ni, Cr)."
)
# Paired chemical fractions determined on the same physical samples within one
# lineage (e.g. total digestion vs leach residue).  The stem before the suffix
# must match for two sample types to form a partition pair.
FRACTION_RULES = {"bulk_vs_leach_residue": ("_bulk", "_leach_residue")}
# Same-sample paired designs need fewer sites than population screening: the
# Wilcoxon signed-rank test retains adequate power for moderate shifts near
# 40 pairs, so T6 applies its own floor instead of --min-samples.
MIN_PAIRED_FRACTION_SAMPLES = 40


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def ev(c):
    return {
        "cohort_id": c["cohort_id"],
        "element": c["element_or_analyte"],
        "medium": c["medium"],
        "sample_type": c["sample_type"],
        "method_family": c["method_family"],
        "tier": c["comparability_tier"],
        "n_quantified_samples": int(c["n_quantified_samples"]),
    }


def bbox_overlap(a, b):
    try:
        return not (
            float(a["bbox_east"]) < float(b["bbox_west"])
            or float(b["bbox_east"]) < float(a["bbox_west"])
            or float(a["bbox_north"]) < float(b["bbox_south"])
            or float(b["bbox_north"]) < float(a["bbox_south"])
        )
    except (ValueError, KeyError):
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--research-dir", required=True)
    ap.add_argument("--output-dir", default=None)
    ap.add_argument("--min-samples", type=int, default=50)
    ap.add_argument("--top-per-type", type=int, default=8)
    args = ap.parse_args()
    out_dir = args.output_dir or args.research_dir
    os.makedirs(out_dir, exist_ok=True)

    cpath = os.path.join(args.research_dir, "analysis_cohorts.csv")
    gpath = os.path.join(args.research_dir, "sampling_priority.geojson")
    cohorts = list(csv.DictReader(open(cpath, encoding="utf-8")))
    usable = [
        c
        for c in cohorts
        if c["comparability_tier"] in USABLE
        and int(c["n_quantified_samples"]) >= args.min_samples
    ]
    cands = []

    # T1 paired surface/deep screening
    by_em = defaultdict(list)
    for c in usable:
        by_em[(c["element_or_analyte"], c["medium"])].append(c)
    for (el, med), cs in sorted(by_em.items()):
        if med not in PAIR_RULES:
            continue
        surf_set, deep_set = PAIR_RULES[med]
        surf = [c for c in cs if c["sample_type"] in surf_set]
        deep = [c for c in cs if c["sample_type"] in deep_set]
        pairs = [
            (s, d)
            for s in surf
            for d in deep
            if s["method_family"] == d["method_family"] and bbox_overlap(s, d)
        ]
        if not pairs:
            continue
        pairs.sort(
            key=lambda sd: (
                -(
                    int(sd[0]["n_quantified_samples"])
                    + int(sd[1]["n_quantified_samples"])
                )
            )
        )
        s, d = pairs[0]
        n = int(s["n_quantified_samples"]) + int(d["n_quantified_samples"])
        cand = {
            "type": "T1_paired_layer_screening",
            "element": el,
            "medium": med,
            "score": n,
            "title": f"{el} surface/deep enrichment screening in {med} ({s['sample_type']} vs {d['sample_type']})",
            "question": (
                f"Is {el} systematically enriched or depleted in {s['sample_type']} relative to "
                f"{d['sample_type']} at the same sites, and is the pattern anthropogenic or geogenic?"
            ),
            "evidence": [ev(s), ev(d)],
            "suggested_design": STAT_TEMPLATE,
            "expected_products": [
                "per-site pair table",
                "ratio + CI + p per element",
                "enrichment map",
                "gap queue for uncovered regions",
            ],
            "caveats": "screening only; ratios conflate pedogenic redistribution with input history",
        }
        if med == "soil" and el in ("Hg", "Pb"):
            cand["worked_example"] = (
                "research-products/paper-demo-20260817 (FOREGS Hg/Pb arXiv draft)"
            )
        cands.append(cand)

    # T2 same-layer method-artifact quantification
    by_ems = defaultdict(list)
    for c in usable:
        by_ems[(c["element_or_analyte"], c["medium"], c["sample_type"])].append(c)
    for (el, med, st), cs in sorted(by_ems.items()):
        fams = sorted({c["method_family"] for c in cs})
        if len(fams) < 2:
            continue
        n = sum(int(c["n_quantified_samples"]) for c in cs)
        cands.append(
            {
                "type": "T2_method_artifact",
                "element": el,
                "medium": med,
                "score": n,
                "title": f"{el} inter-method comparability in {st} ({' vs '.join(fams)})",
                "question": (
                    f"How large is the same-sample measurement offset for {el} in {st} between "
                    f"{' and '.join(fams)}, and can a transfer model make the cohorts poolable?"
                ),
                "evidence": [ev(c) for c in sorted(cs, key=lambda x: x["cohort_id"])],
                "suggested_design": (
                    "join determinations on shared sample identifiers; paired ratio or "
                    "log-offset model per element; report offset, spread, and covariate "
                    "dependence (e.g. refractory host phases)"
                ),
                "expected_products": [
                    "same-sample offset table",
                    "transfer-model coefficients",
                    "poolability verdict per cohort pair",
                ],
                "caveats": "requires shared sample identifiers across determinations within one source",
            }
        )

    # T3 single-source dependency risk
    for (el, med), cs in sorted(by_em.items()):
        total = sum(int(c["n_quantified_samples"]) for c in cs)
        srcs = {c["dominant_source_id"] for c in cs}
        if (
            total >= 500
            and len(srcs) == 1
            and all(int(c["n_sources"]) == 1 for c in cs)
        ):
            src = next(iter(srcs))
            cands.append(
                {
                    "type": "T3_single_source_dependency",
                    "element": el,
                    "medium": med,
                    "score": total,
                    "title": f"{el} in {med}: all evidence from a single source ({src})",
                    "question": (
                        f"Every usable {el}/{med} cohort descends from {src}; which independent "
                        f"survey could falsify or confirm its patterns?"
                    ),
                    "evidence": [
                        ev(c) for c in sorted(cs, key=lambda x: x["cohort_id"])
                    ],
                    "suggested_design": (
                        "treat as acquisition target: locate an independent open survey, "
                        "admit it through D1 source acceptance, re-run cohorts, compare"
                    ),
                    "expected_products": [
                        "candidate source shortlist",
                        "cross-survey consistency check",
                    ],
                    "caveats": "proposal only; acquisition must go through the D1 evidence chain",
                }
            )

    # T4 gap-driven regional topics
    gj = json.load(open(gpath, encoding="utf-8"))
    by_region = defaultdict(list)
    for f in gj.get("features", []):
        p = f.get("properties", {})
        by_region[p.get("macroregion") or "unknown"].append(p)
    for region, feats in sorted(by_region.items()):
        elements = sorted(
            {e for p in feats for e in (p.get("required_elements") or [])}
        )
        countries = sorted(
            {p.get("country_name") for p in feats if p.get("country_name")}
        )[:8]
        cands.append(
            {
                "type": "T4_coverage_gap",
                "element": ",".join(elements[:6]),
                "medium": "region",
                "score": len(feats),
                "title": f"{region}: {len(feats)} prioritized coverage-repair tasks",
                "question": (
                    f"Which open sources can close the {region} gaps (e.g. {', '.join(countries[:4])}) "
                    f"for {', '.join(elements[:4])}, and what does the closed gap change?"
                ),
                "evidence": [
                    {
                        "gap_tasks": len(feats),
                        "example_countries": countries,
                        "required_elements": elements,
                    }
                ],
                "suggested_design": (
                    "follow discovery_platform_sequence per task; each admitted source "
                    "re-enters the standard pipeline; report coverage delta"
                ),
                "expected_products": ["acquisition plan", "coverage-delta report"],
                "caveats": "acquisition planning only; no new claims until data are admitted",
            }
        )

    # T5 cross-media coupling
    by_el = defaultdict(lambda: defaultdict(int))
    for c in usable:
        by_el[c["element_or_analyte"]][c["medium"]] += int(c["n_quantified_samples"])
    for el, media in sorted(by_el.items()):
        if media.get("soil", 0) >= 200 and (
            media.get("water", 0) >= 200 or media.get("sediment", 0) >= 200
        ):
            partner = "water" if media.get("water", 0) >= 200 else "sediment"
            cands.append(
                {
                    "type": "T5_cross_media",
                    "element": el,
                    "medium": f"soil+{partner}",
                    "score": media["soil"] + media[partner],
                    "title": f"{el}: soil-{partner} coupling screening",
                    "question": (
                        f"Do spatial patterns of {el} in soil and {partner} co-vary at basin scale, "
                        f"consistent with export from the soil reservoir?"
                    ),
                    "evidence": [
                        {"element": el, "medium": m, "n_quantified_samples": n}
                        for m, n in sorted(media.items())
                    ],
                    "suggested_design": (
                        "aggregate both media to shared spatial units; rank-correlate; "
                        "stratify by method family and confidence band"
                    ),
                    "expected_products": [
                        "basin-level co-variation table",
                        "coupling map",
                    ],
                    "caveats": "correlation screening only; no transport-mechanism claims",
                }
            )

    # T6 paired chemical-fraction partition screening
    fraction_pool = [
        c
        for c in cohorts
        if c["comparability_tier"] in USABLE
        and int(c["n_quantified_samples"]) >= MIN_PAIRED_FRACTION_SAMPLES
    ]
    by_emf = defaultdict(list)
    for c in fraction_pool:
        by_emf[(c["element_or_analyte"], c["medium"], c["method_family"])].append(c)
    for (el, med, fam), cs in sorted(by_emf.items()):
        by_stem = defaultdict(dict)
        for c in cs:
            st = c["sample_type"]
            for rule, (bulk_sfx, part_sfx) in sorted(FRACTION_RULES.items()):
                if st.endswith(bulk_sfx):
                    by_stem[(st[: -len(bulk_sfx)], rule)]["bulk"] = c
                elif st.endswith(part_sfx):
                    by_stem[(st[: -len(part_sfx)], rule)]["partial"] = c
        for (stem, rule), pair in sorted(by_stem.items()):
            b = pair.get("bulk")
            p = pair.get("partial")
            if not b or not p or not bbox_overlap(b, p):
                continue
            n = int(b["n_quantified_samples"]) + int(p["n_quantified_samples"])
            # The estimand is the operational paired concentration contrast
            # between the two fractions of the same physical sample.  A
            # physical "leachable share" would need leachate or residue mass
            # recovery, which these archives do not publish; asking for it
            # makes every pilot fail closed on an unidentifiable quantity.
            cands.append(
                {
                    "type": "T6_paired_fraction_partition",
                    "element": el,
                    "medium": med,
                    "score": n,
                    "title": (
                        f"{el} bulk vs {rule} fraction contrast in {stem} "
                        f"({b['sample_type']} vs {p['sample_type']})"
                    ),
                    "question": (
                        f"For the same physical {stem} samples, how large and how "
                        f"consistent is the paired {el} concentration contrast between "
                        f"the {b['sample_type']} and {p['sample_type']} determinations, "
                        f"and does that operational contrast vary spatially?"
                    ),
                    "evidence": [ev(b), ev(p)],
                    "suggested_design": (
                        "join bulk and partial determinations on shared sample "
                        "identifiers within one lineage; per-sample paired log-ratio "
                        "(partial / bulk) of concentrations; report the median ratio, a "
                        "dependence-aware 95% interval, Wilcoxon signed-rank on paired "
                        "log concentrations; map the ratio; sensitivity: alternative "
                        "normalization and independent geogenic reference elements"
                    ),
                    "expected_products": [
                        "per-sample fraction-contrast table",
                        "paired concentration-ratio estimate + interval per element",
                        "spatial contrast map",
                        "robustness table (normalization variants)",
                    ],
                    "caveats": (
                        "requires shared sample identifiers between fractions within "
                        "one source; the contrast is an operational concentration "
                        "ratio, not a physical leachable mass share (no leachate or "
                        "residue mass recovery is published); partition screening "
                        "only, no mechanistic leaching claims"
                    ),
                }
            )

    # Rank feasibility within type, cap, and preserve a stable order.  This score
    # is deliberately not called novelty or paper quality: those require the
    # hash-bound pilot and primary-literature frontier gate.
    final = []
    for t in sorted({c["type"] for c in cands}):
        group = sorted(
            [c for c in cands if c["type"] == t],
            key=lambda c: (-c["score"], c["element"], c["medium"]),
        )
        final.extend(group[: args.top_per_type])
    for i, c in enumerate(final, 1):
        c["candidate_id"] = f"dc-{i:03d}"
        empirical = c["type"] in {
            "T1_paired_layer_screening",
            "T2_method_artifact",
            "T5_cross_media",
            "T6_paired_fraction_partition",
        }
        c["research_readiness"] = {
            "paper_track": (
                "empirical_candidate" if empirical else "acquisition_or_audit_plan"
            ),
            "row_level_pilot_required": True,
            "paper_eligible_before_pilot": False,
            "paper_eligible_before_acquisition": empirical,
            "frontier_status": "needs_primary_literature_verification",
            "visual_evidence_potential": (
                [
                    "primary_result",
                    "spatial_pattern",
                    "robustness_or_external_validation",
                ]
                if empirical
                else ["coverage_gap", "acquisition_priority"]
            ),
            "routing_if_unsupported": ("candidate_selection" if empirical else "D1"),
        }
        c["ranking_basis"] = {
            "score_meaning": (
                "within-template evidence volume or gap-task count; not novelty, "
                "significance, or publication readiness"
            ),
            "requires_quality_gate": True,
        }

    receipt = {
        "inputs": {
            os.path.basename(cpath): sha256(cpath),
            os.path.basename(gpath): sha256(gpath),
        },
        "parameters": {
            "min_samples": args.min_samples,
            "top_per_type": args.top_per_type,
            "paired_fraction_min_samples": MIN_PAIRED_FRACTION_SAMPLES,
        },
        "counts": {
            "cohorts_total": len(cohorts),
            "cohorts_usable": len(usable),
            "candidates": len(final),
        },
    }
    out = {"discovery_candidates": final, "receipt": receipt}
    jpath = os.path.join(out_dir, "discovery_candidates.json")
    json.dump(out, open(jpath, "w", encoding="utf-8"), indent=2, ensure_ascii=False)

    lines = [
        "# Discovery candidates",
        "",
        f"{len(final)} candidates from {len(usable)} usable cohorts. Screening proposals only;",
        "every candidate points at cohort/gap evidence inside this run.",
        "",
    ]
    for c in final:
        lines.append(f"## {c['candidate_id']} [{c['type']}] {c['title']}")
        lines.append(f"- question: {c['question']}")
        lines.append(
            f"- evidence: {json.dumps(c['evidence'], ensure_ascii=False)[:300]}"
        )
        lines.append(f"- design: {c['suggested_design']}")
        if "worked_example" in c:
            lines.append(f"- worked example: {c['worked_example']}")
        lines.append(f"- caveats: {c['caveats']}")
        lines.append("")
    open(os.path.join(out_dir, "discovery_candidates.md"), "w", encoding="utf-8").write(
        chr(10).join(lines)
    )
    print(f"wrote {len(final)} candidates -> {jpath}")


if __name__ == "__main__":
    main()
