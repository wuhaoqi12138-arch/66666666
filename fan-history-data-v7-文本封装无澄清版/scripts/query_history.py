#!/usr/bin/env python3
"""Query the fan historical-data package without loading the full corpus.

This utility reports historical evidence and statistical anomaly signals.  It
does not decide current-project compliance and never converts historical values
into tender requirements.
"""

from __future__ import annotations

import argparse
import base64
import gzip
import io
import json
import lzma
import math
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
REFERENCES = ROOT / "references"
RECORDS_PATH = REFERENCES / "history-records.jsonl.xz.b64"
CASES_PATH = REFERENCES / "history-cases.jsonl.xz.b64"
MANIFEST_PATH = REFERENCES / "source-manifest.json"
BUILD_SUMMARY_PATH = REFERENCES / "build-summary.json"
RAW_CLEAR_PATH = REFERENCES / "raw-clear-corpus.jsonl.xz.b64"
RAW_AGREEMENT_PATH = REFERENCES / "raw-agreement-corpus.jsonl.xz.b64"

LEGACY_DATA_PATHS = {
    RECORDS_PATH: (REFERENCES / "history-records.jsonl.xz", REFERENCES / "history-records.jsonl.gz", REFERENCES / "history-records.jsonl"),
    CASES_PATH: (REFERENCES / "history-cases.jsonl.xz", REFERENCES / "history-cases.jsonl"),
    RAW_CLEAR_PATH: (REFERENCES / "raw-clear-corpus.jsonl.xz", REFERENCES / "raw-clear-corpus.jsonl"),
    RAW_AGREEMENT_PATH: (REFERENCES / "raw-agreement-corpus.jsonl.xz", REFERENCES / "raw-agreement-corpus.jsonl"),
}

DEFAULT_UNITS = {
    "设计流量": "Nm3/h",
    "工况流量": "m3/h",
    "静压": "Pa",
    "全压": "Pa",
    "轴功率": "kW",
    "电机功率": "kW",
    "电机效率": "%",
    "电机功率因数": "%",
    "风机效率": "%",
    "风机效率_TB": "%",
    "风机效率_MCR": "%",
    "风机效率_110%MCR": "%",
    "叶轮重量": "kg",
    "电机重量": "kg",
    "风机本体重量": "kg",
    "设计吸入温度": "℃",
    "设计温度": "℃",
    "转速": "r/min",
    "噪声": "dB(A)",
}

CONTEXT_MAP = {
    "design_flow": "设计流量",
    "working_flow": "工况流量",
    "static_pressure": "静压",
    "total_pressure": "全压",
    "temperature": "设计吸入温度",
    "speed": "转速",
}


def emit(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def normalize_text(value: Any) -> str:
    return "" if value is None else "".join(str(value).lower().split())


def normalize_unit(value: str) -> str:
    text = normalize_text(value).replace("³", "3")
    aliases = {
        "nm3/h": "Nm3/h",
        "m3/h": "m3/h",
        "pa": "Pa",
        "kpa": "kPa",
        "kw": "kW",
        "%": "%",
        "kg": "kg",
        "℃": "℃",
        "°c": "℃",
        "r/min": "r/min",
        "rpm": "r/min",
        "db(a)": "dB(A)",
        "dba": "dB(A)",
    }
    return aliases.get(text, value.strip())


def resolve_data_path(path: Path) -> Path:
    """Prefer importer-safe Base64 text, while reading older local packages."""
    if path.exists():
        return path
    for legacy in LEGACY_DATA_PATHS.get(path, ()):
        if legacy.exists():
            return legacy
    return path


def iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    path = resolve_data_path(path)
    if path.name.endswith(".xz.b64"):
        try:
            encoded = b"".join(path.read_bytes().split())
            payload = base64.b64decode(encoded, validate=True)
        except Exception as exc:
            raise RuntimeError(f"历史数据文件不是有效 Base64：{path}") from exc
        stream_factory = lambda: lzma.open(io.BytesIO(payload), "rt", encoding="utf-8")
    elif path.suffix == ".xz":
        stream_factory = lambda: lzma.open(path, "rt", encoding="utf-8")
    elif path.suffix == ".gz":
        stream_factory = lambda: gzip.open(path, "rt", encoding="utf-8")
    else:
        stream_factory = lambda: open(path, "rt", encoding="utf-8")
    with stream_factory() as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def data_assets_status() -> dict[str, Any]:
    required = {
        "records": RECORDS_PATH,
        "cases": CASES_PATH,
        "raw_clear": RAW_CLEAR_PATH,
        "raw_agreement": RAW_AGREEMENT_PATH,
    }
    assets = {}
    for key, path in required.items():
        actual = resolve_data_path(path)
        assets[key] = {
            "expected_file": path.name,
            "available": actual.exists(),
            "file": actual.name if actual.exists() else None,
            "format": "base64+xz" if actual.name.endswith(".xz.b64") else (actual.suffix.lstrip(".") if actual.exists() else None),
        }
    return {
        "complete": all(item["available"] for item in assets.values()),
        "assets": assets,
    }


def load_cases() -> dict[str, dict[str, Any]]:
    return {row["case_id"]: row for row in iter_jsonl(CASES_PATH)}


def text_match(haystack: str, needle: str) -> bool:
    return not needle or normalize_text(needle) in normalize_text(haystack)


def record_matches(record: dict[str, Any], args: argparse.Namespace, numeric_only: bool = False, ignore_supplier: bool = False) -> bool:
    if getattr(args, "fan_type", "") and not text_match(record.get("fan_type", ""), args.fan_type):
        return False
    parameter = getattr(args, "parameter", "")
    if parameter and not (
        text_match(record.get("parameter_canonical", ""), parameter)
        or text_match(record.get("parameter_raw", ""), parameter)
    ):
        return False
    supplier = "" if ignore_supplier else getattr(args, "supplier", "")
    if supplier and not (
        text_match(record.get("supplier_canonical", ""), supplier)
        or text_match(record.get("supplier_raw", ""), supplier)
    ):
        return False
    if getattr(args, "project", "") and not (
        text_match(record.get("project", ""), args.project)
        or text_match(record.get("source_project", ""), args.project)
    ):
        return False
    if getattr(args, "condition", "") and not text_match(record.get("operating_condition", ""), args.condition):
        return False
    if getattr(args, "source_id", "") and record.get("source_id") != args.source_id:
        return False
    if numeric_only and (not record.get("analysis_eligible") or record.get("numeric_value") is None):
        return False
    return True


def record_unit(record: dict[str, Any]) -> str:
    unit = record.get("normalized_unit") or record.get("unit_raw") or DEFAULT_UNITS.get(record.get("parameter_canonical", ""), "")
    return normalize_unit(unit)


def citation(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "project": record.get("project", ""),
        "fan_type": record.get("fan_type", ""),
        "supplier": record.get("supplier_canonical") or record.get("supplier_raw", ""),
        "parameter": record.get("parameter_raw", ""),
        "value_raw": record.get("historical_value_raw", ""),
        "condition": record.get("operating_condition", ""),
        "source_id": record.get("source_id", ""),
        "source_batch": record.get("source_batch", ""),
        "source_file": record.get("source_file", ""),
        "location": record.get("location", ""),
        "evidence_raw": record.get("evidence_raw", ""),
    }


def deduplicate(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for record in records:
        key = (
            record.get("project"),
            record.get("fan_type"),
            record.get("supplier_canonical") or record.get("supplier_raw"),
            record.get("parameter_canonical"),
            record.get("operating_condition"),
            record.get("numeric_value"),
            record_unit(record),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(record)
    return result


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def statistical_summary(records: list[dict[str, Any]], current_value: float | None = None) -> dict[str, Any]:
    values = [float(record["numeric_value"]) for record in records if record.get("numeric_value") is not None]
    if not values:
        return {
            "sample_count": 0,
            "project_count": 0,
            "supplier_count": 0,
            "interpretation": "无可用同口径数值样本",
            "anomaly_label": "样本不足",
        }
    q1 = percentile(values, 0.25)
    q3 = percentile(values, 0.75)
    median = statistics.median(values)
    summary: dict[str, Any] = {
        "sample_count": len(values),
        "project_count": len({record.get("project") for record in records}),
        "supplier_count": len({record.get("supplier_canonical") or record.get("supplier_raw") for record in records}),
        "min": min(values),
        "q1": round(q1, 6),
        "median": round(median, 6),
        "q3": round(q3, 6),
        "max": max(values),
        "iqr": round(q3 - q1, 6),
        "unit": record_unit(records[0]),
        "anomaly_label": "未计算",
        "interpretation": "历史统计仅用于参考和异常提示，不是招标门槛。",
    }
    if current_value is None:
        return summary
    summary["current_value"] = current_value
    summary["relative_to_median_pct"] = None if median == 0 else round((current_value - median) / abs(median) * 100, 2)
    if len(values) >= 5:
        iqr = q3 - q1
        if iqr == 0:
            is_outlier = current_value != median
            lower = upper = median
        else:
            lower = q1 - 1.5 * iqr
            upper = q3 + 1.5 * iqr
            is_outlier = current_value < lower or current_value > upper
        if min(values) >= 0:
            lower = max(0.0, lower)
        summary["statistical_reference_bounds"] = [round(lower, 6), round(upper, 6)]
        summary["anomaly_label"] = "统计异常待核" if is_outlier else "未见统计异常"
    elif len(values) >= 3:
        is_outlier = current_value < min(values) or current_value > max(values)
        summary["statistical_reference_bounds"] = [min(values), max(values)]
        summary["anomaly_label"] = "历史区间外待核（小样本）" if is_outlier else "历史小样本区间内"
    else:
        summary["statistical_reference_bounds"] = None
        summary["anomaly_label"] = "样本不足，仅列案例"
    return summary


def case_context_number(case: dict[str, Any], parameter: str, condition: str = "") -> float | None:
    candidates = case.get("project_conditions", {}).get(parameter, [])
    if not candidates:
        return None
    if condition:
        condition_hits = [item for item in candidates if text_match(item.get("condition", ""), condition)]
        if condition_hits:
            candidates = condition_hits
    values = [item.get("numeric_value") for item in candidates if item.get("numeric_value") is not None]
    return float(values[0]) if values else None


def context_similarity(record: dict[str, Any], case: dict[str, Any], current_context: dict[str, float]) -> tuple[float | None, float]:
    if not current_context:
        return None, 1.0
    components: list[float] = []
    for key, current in current_context.items():
        parameter = CONTEXT_MAP[key]
        historical = case_context_number(case, parameter, record.get("operating_condition", ""))
        if historical is None:
            continue
        denominator = max(abs(current), 1.0)
        relative_difference = abs(historical - current) / denominator
        components.append(max(0.0, 1.0 - relative_difference))
    completeness = len(components) / len(current_context)
    return (sum(components) / len(components) if components else None), completeness


def compact_record(record: dict[str, Any], similarity: float | None = None, completeness: float | None = None) -> dict[str, Any]:
    result = citation(record)
    result.update(
        {
            "record_id": record.get("record_id"),
            "case_id": record.get("case_id"),
            "numeric_value": record.get("numeric_value"),
            "unit": record_unit(record),
            "value_provenance": record.get("value_provenance", ""),
            "record_role": record.get("record_role", ""),
        }
    )
    if similarity is not None:
        result["context_similarity"] = round(similarity, 4)
        result["context_completeness"] = round(completeness or 0.0, 4)
    return result


def command_coverage(_args: argparse.Namespace) -> None:
    summary = json.loads(BUILD_SUMMARY_PATH.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    status_counts = Counter(item.get("extraction_status", "") for item in manifest)
    no_text = [
        {
            "source_id": item["source_id"],
            "batch": item["source_batch"],
            "source_file": item["original_file"],
            "project": item.get("project_guess", ""),
        }
        for item in manifest
        if item.get("extraction_status") == "no-text-layer"
    ]
    emit(
        {
            "data_assets": data_assets_status(),
            "data_summary": summary,
            "extraction_status_counts": status_counts,
            "ocr_or_manual_review_required": no_text,
            "mandatory_boundary": "本库只用于历史对照、区间参考和异常提示；当前项目合规性只能依据当前招标文件及已批准澄清。",
        }
    )


def command_records(args: argparse.Namespace) -> None:
    rows = [record for record in iter_jsonl(RECORDS_PATH) if record_matches(record, args, numeric_only=args.numeric_only)]
    if args.unit:
        target = normalize_unit(args.unit)
        rows = [record for record in rows if record_unit(record) == target]
    if args.deduplicate:
        rows = deduplicate(rows)
    emit(
        {
            "match_count": len(rows),
            "returned": min(len(rows), args.limit),
            "records": [compact_record(record) for record in rows[: args.limit]],
            "note": "原文、项目、设备、供应商、文件和位置均随记录返回；不要脱离工况引用单个历史值。",
        }
    )


def command_sources(args: argparse.Namespace) -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    rows = []
    for item in manifest:
        if args.source_id and item.get("source_id") != args.source_id:
            continue
        if args.corpus != "all" and item.get("corpus") != args.corpus:
            continue
        if args.project and not text_match(item.get("project_guess", ""), args.project):
            continue
        if args.status and not text_match(item.get("extraction_status", ""), args.status):
            continue
        if args.fan_type and not any(text_match(value, args.fan_type) for value in item.get("fan_types", [])):
            continue
        rows.append(item)
    emit({"match_count": len(rows), "returned": min(len(rows), args.limit), "sources": rows[: args.limit]})


def command_search(args: argparse.Namespace) -> None:
    corpus_paths: list[Path] = []
    if args.corpus in ("all", "clear"):
        corpus_paths.append(RAW_CLEAR_PATH)
    if args.corpus in ("all", "agreement"):
        corpus_paths.append(RAW_AGREEMENT_PATH)
    hits: list[dict[str, Any]] = []
    query = normalize_text(args.query)
    for path in corpus_paths:
        for row in iter_jsonl(path):
            if args.source_id and row.get("source_id") != args.source_id:
                continue
            if args.project and not text_match(row.get("project_guess", ""), args.project):
                continue
            if args.fan_type and not any(text_match(item, args.fan_type) for item in row.get("fan_types", [])):
                continue
            if query not in normalize_text(row.get("text", "")):
                continue
            hits.append(
                {
                    "source_id": row.get("source_id"),
                    "source_file": row.get("source_file"),
                    "project": row.get("project_guess"),
                    "fan_types": row.get("fan_types", []),
                    "corpus": row.get("corpus"),
                    "location": row.get("location"),
                    "text": row.get("text"),
                }
            )
            if len(hits) >= args.limit:
                break
        if len(hits) >= args.limit:
            break
    emit(
        {
            "query": args.query,
            "returned": len(hits),
            "hits": hits,
            "note": "全文命中可能来自协议条款、表格或清标结论；必须阅读上下文后再用于分析。",
        }
    )


def select_comparable_records(args: argparse.Namespace) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], dict[str, Any]]:
    base = [record for record in iter_jsonl(RECORDS_PATH) if record_matches(record, args, numeric_only=True, ignore_supplier=True)]
    if args.unit:
        target_unit = normalize_unit(args.unit)
        base = [record for record in base if record_unit(record) == target_unit]
    base = deduplicate(base)
    cases = load_cases()
    current_context = {
        key: float(getattr(args, key))
        for key in CONTEXT_MAP
        if getattr(args, key, None) is not None
    }
    scored: list[tuple[dict[str, Any], float | None, float]] = []
    for record in base:
        case = cases.get(record.get("case_id"), {})
        similarity, completeness = context_similarity(record, case, current_context)
        scored.append((record, similarity, completeness))
    if current_context:
        strict = [item for item in scored if item[1] is not None and item[1] >= args.min_similarity and item[2] >= args.min_completeness]
        if len(strict) >= 3:
            selected = strict
            mode = "按已提供项目条件筛选的相近工况样本"
            warning = "仍需人工确认介质、温度、系统边界、裕量和设计责任是否可比。"
        else:
            selected = scored
            mode = "相近工况样本不足，退回同风机类型/同参数宽口径样本"
            warning = "未能形成至少3条工况相近记录；统计结果置信度低，只能用于提示复核。"
    else:
        selected = scored
        mode = "未提供项目条件，使用同风机类型/同参数宽口径样本"
        warning = "缺少流量、压力、温度等项目条件，不能据此判断本次方案合理或不合理。"
    selected.sort(key=lambda item: (-(item[1] if item[1] is not None else -1), item[0].get("project", "")))
    selected_records = [item[0] for item in selected]
    score_map = {item[0]["record_id"]: {"similarity": item[1], "completeness": item[2]} for item in selected}
    return selected_records, score_map, {"mode": mode, "warning": warning, "provided_context": current_context, "candidate_count": len(base), "selected_count": len(selected_records)}


def records_with_scores(records: list[dict[str, Any]], score_map: dict[str, dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    result = []
    for record in records[:limit]:
        score = score_map.get(record["record_id"], {})
        result.append(compact_record(record, score.get("similarity"), score.get("completeness")))
    return result


def summary_text(label: str, summary: dict[str, Any], args: argparse.Namespace) -> str:
    if summary.get("sample_count", 0) == 0:
        return f"{label}：未检索到可用的同口径数值样本。"
    unit = summary.get("unit") or args.unit or ""
    range_text = f"{summary['min']}～{summary['max']}{unit}，中位数{summary['median']}{unit}"
    return (
        f"{label}：检索到{summary['sample_count']}条去重样本，涉及{summary['project_count']}个项目；"
        f"历史范围{range_text}。本次值{args.value}{unit}，判断为“{summary['anomaly_label']}”。"
        "历史数据只用于参考和异常提示，不能替代本项目招标要求。"
    )


def command_analyze(args: argparse.Namespace) -> None:
    selected, score_map, comparability = select_comparable_records(args)
    current_value = float(args.value)
    same_supplier: list[dict[str, Any]] = []
    other_suppliers: list[dict[str, Any]] = []
    for record in selected:
        if args.supplier and (
            text_match(record.get("supplier_canonical", ""), args.supplier)
            or text_match(record.get("supplier_raw", ""), args.supplier)
        ):
            same_supplier.append(record)
        else:
            other_suppliers.append(record)
    same_summary = statistical_summary(same_supplier, current_value)
    other_summary = statistical_summary(other_suppliers, current_value)
    anomaly = same_summary.get("anomaly_label", "") not in {"未见统计异常", "历史小样本区间内", "样本不足，仅列案例", "样本不足"} or other_summary.get("anomaly_label", "") not in {"未见统计异常", "历史小样本区间内", "样本不足，仅列案例", "样本不足"}
    if anomaly:
        clarification = (
            "本项与历史可比项目数据存在异常信号，请说明本次取值的设计依据、适用工况、关联参数，"
            "并明确其对设备性能、供货范围及报价的影响；请同时提供投标文件中的支撑位置。"
        )
    else:
        clarification = "如本项已由当前招标要求和投标承诺充分确定，则无需仅因历史数据发起澄清；历史结果留作内部参考。"
    emit(
        {
            "mandatory_boundary": "历史数据不构成当前招标门槛；是否满足只能依据当前招标文件及已批准澄清。",
            "query": {
                "fan_type": args.fan_type,
                "parameter": args.parameter,
                "current_value": current_value,
                "unit": args.unit,
                "supplier": args.supplier,
                "condition": args.condition,
            },
            "comparability": comparability,
            "same_supplier_history": {
                "summary": same_summary,
                "suggested_analysis": summary_text("同一供应商历史项目", same_summary, args),
                "evidence": records_with_scores(same_supplier, score_map, args.limit),
            },
            "other_supplier_history": {
                "summary": other_summary,
                "suggested_analysis": summary_text("其他供应商历史项目", other_summary, args),
                "evidence": records_with_scores(other_suppliers, score_map, args.limit),
            },
            "suggested_clarification": clarification,
            "confidentiality_note": "对外澄清不得披露其他投标人的名称、具体方案、原始数值或内部评价。",
        }
    )


def add_common_filters(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--fan-type", default="")
    parser.add_argument("--parameter", default="")
    parser.add_argument("--supplier", default="")
    parser.add_argument("--project", default="")
    parser.add_argument("--condition", default="")
    parser.add_argument("--source-id", default="")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    coverage = subparsers.add_parser("coverage", help="Show corpus coverage and extraction limits")
    coverage.set_defaults(func=command_coverage)

    records = subparsers.add_parser("records", help="List normalized historical records")
    add_common_filters(records)
    records.add_argument("--unit", default="")
    records.add_argument("--limit", type=int, default=20)
    records.add_argument("--numeric-only", action="store_true")
    records.add_argument("--deduplicate", action="store_true")
    records.set_defaults(func=command_records)

    sources = subparsers.add_parser("sources", help="List source files and extraction status")
    sources.add_argument("--source-id", default="")
    sources.add_argument("--corpus", choices=("all", "clear", "agreement"), default="all")
    sources.add_argument("--project", default="")
    sources.add_argument("--fan-type", default="")
    sources.add_argument("--status", default="")
    sources.add_argument("--limit", type=int, default=50)
    sources.set_defaults(func=command_sources)

    search = subparsers.add_parser("search", help="Search exact wording in clear sheets and agreements")
    search.add_argument("--query", required=True)
    search.add_argument("--corpus", choices=("all", "clear", "agreement"), default="all")
    search.add_argument("--source-id", default="")
    search.add_argument("--project", default="")
    search.add_argument("--fan-type", default="")
    search.add_argument("--limit", type=int, default=20)
    search.set_defaults(func=command_search)

    analyze = subparsers.add_parser("analyze", help="Compare one current value with historical cases")
    analyze.add_argument("--fan-type", required=True)
    analyze.add_argument("--parameter", required=True)
    analyze.add_argument("--value", required=True, type=float)
    analyze.add_argument("--unit", required=True)
    analyze.add_argument("--supplier", default="")
    analyze.add_argument("--condition", default="")
    analyze.add_argument("--project", default="")
    analyze.add_argument("--source-id", default="")
    analyze.add_argument("--design-flow", type=float)
    analyze.add_argument("--working-flow", type=float)
    analyze.add_argument("--static-pressure", type=float)
    analyze.add_argument("--total-pressure", type=float)
    analyze.add_argument("--temperature", type=float)
    analyze.add_argument("--speed", type=float)
    analyze.add_argument("--min-similarity", type=float, default=0.5)
    analyze.add_argument("--min-completeness", type=float, default=0.5)
    analyze.add_argument("--limit", type=int, default=8)
    analyze.set_defaults(func=command_analyze)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    required_by_command = {
        "records": (RECORDS_PATH,),
        "search": ((RAW_CLEAR_PATH, RAW_AGREEMENT_PATH) if getattr(args, "corpus", "all") == "all" else ((RAW_CLEAR_PATH,) if args.corpus == "clear" else (RAW_AGREEMENT_PATH,))),
        "analyze": (RECORDS_PATH, CASES_PATH),
    }
    missing = [path.name for path in required_by_command.get(args.command, ()) if not resolve_data_path(path).exists()]
    if missing:
        emit(
            {
                "error": "history_data_incomplete",
                "missing_assets": missing,
                "message": "历史库资产不完整或未成功导入；请确认 references 中的四个 .jsonl.xz.b64 单文件均存在。",
            }
        )
        return 2
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
