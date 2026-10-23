from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

MAX_DEPTH = 5
MAX_LEAVES = 10

SCHEMA_INVALID = "SCHEMA_INVALID"
TOO_FEW_CHILDREN = "TOO_FEW_CHILDREN"
EMPTY_SUBTRACT = "EMPTY_SUBTRACT"
MAX_DEPTH_EXCEEDED = "MAX_DEPTH_EXCEEDED"
MAX_LEAVES_EXCEEDED = "MAX_LEAVES_EXCEEDED"
UNKNOWN_CONDITION = "UNKNOWN_CONDITION"
INACTIVE_CONDITION = "INACTIVE_CONDITION"
PROFILE_MISMATCH = "PROFILE_MISMATCH"


@dataclass(frozen=True)
class ConditionInfo:
    profile_id: str
    active: bool


@dataclass(frozen=True)
class EvalResult:
    codes: list[str]
    matches: dict[str, list[str]]
    excluded: list[str]


def validate_definition(definition: object, conditions: Mapping[str, ConditionInfo]) -> list[str]:
    if not _is_definition_schema_valid(definition):
        return [SCHEMA_INVALID]

    profile_id = definition["profileId"]
    expr = definition["expr"]
    issues: set[str] = set()
    _collect_validation_issues(expr, conditions, profile_id, 1, issues)
    return sorted(issues)


def leaf_condition_ids(expr: Mapping[str, Any]) -> list[str]:
    ordered_ids: list[str] = []
    seen: set[str] = set()

    def walk(node: Mapping[str, Any]) -> None:
        node_type = node.get("type")
        if node_type == "condition":
            condition_id = node["conditionId"]
            if condition_id not in seen:
                seen.add(condition_id)
                ordered_ids.append(condition_id)
            return
        if node_type in {"and", "or"}:
            for child in node["children"]:
                walk(child)
            return
        if node_type == "exclude":
            walk(node["base"])
            for child in node["subtract"]:
                walk(child)

    walk(expr)
    return ordered_ids


def evaluate(expr: Mapping[str, Any], sets: Mapping[str, frozenset[str]]) -> EvalResult:
    result_codes, excluded_candidates = _evaluate_node(expr, sets)
    sorted_codes = sorted(result_codes)
    ordered_leaf_ids = leaf_condition_ids(expr)
    matches = {
        code: [condition_id for condition_id in ordered_leaf_ids if code in sets.get(condition_id, frozenset())]
        for code in sorted_codes
    }
    excluded = sorted(excluded_candidates - result_codes)
    return EvalResult(codes=sorted_codes, matches=matches, excluded=excluded)


def _is_definition_schema_valid(definition: object) -> bool:
    if not isinstance(definition, dict):
        return False
    if set(definition) != {"schemaVersion", "profileId", "exchange", "expr"}:
        return False
    schema_version = definition["schemaVersion"]
    if type(schema_version) is not int or schema_version != 1:
        return False
    if not isinstance(definition["profileId"], str) or not definition["profileId"]:
        return False
    if definition["exchange"] != "K":
        return False
    return _is_expr_schema_valid(definition["expr"])


def _is_expr_schema_valid(expr: object) -> bool:
    if not isinstance(expr, dict):
        return False

    node_type = expr.get("type")
    if not isinstance(node_type, str):
        return False

    if node_type == "condition":
        return set(expr) == {"type", "conditionId"} and isinstance(expr.get("conditionId"), str) and bool(expr["conditionId"])

    if node_type in {"and", "or"}:
        if set(expr) != {"type", "children"}:
            return False
        children = expr.get("children")
        return isinstance(children, list) and all(_is_expr_schema_valid(child) for child in children)

    if node_type == "exclude":
        if set(expr) != {"type", "base", "subtract"}:
            return False
        subtract = expr.get("subtract")
        return _is_expr_schema_valid(expr.get("base")) and isinstance(subtract, list) and all(
            _is_expr_schema_valid(child) for child in subtract
        )

    return False


def _collect_validation_issues(
    expr: Mapping[str, Any],
    conditions: Mapping[str, ConditionInfo],
    profile_id: str,
    depth: int,
    issues: set[str],
) -> int:
    if depth > MAX_DEPTH:
        issues.add(MAX_DEPTH_EXCEEDED)

    node_type = expr["type"]

    if node_type == "condition":
        condition_id = expr["conditionId"]
        condition = conditions.get(condition_id)
        if condition is None:
            issues.add(UNKNOWN_CONDITION)
        else:
            if condition.profile_id != profile_id:
                issues.add(PROFILE_MISMATCH)
            if not condition.active:
                issues.add(INACTIVE_CONDITION)
        return 1

    if node_type in {"and", "or"}:
        children = expr["children"]
        if len(children) < 2:
            issues.add(TOO_FEW_CHILDREN)
        leaves = 0
        for child in children:
            leaves += _collect_validation_issues(child, conditions, profile_id, depth + 1, issues)
        if leaves > MAX_LEAVES:
            issues.add(MAX_LEAVES_EXCEEDED)
        return leaves

    subtract = expr["subtract"]
    if len(subtract) < 1:
        issues.add(EMPTY_SUBTRACT)

    leaves = _collect_validation_issues(expr["base"], conditions, profile_id, depth + 1, issues)
    for child in subtract:
        leaves += _collect_validation_issues(child, conditions, profile_id, depth + 1, issues)
    if leaves > MAX_LEAVES:
        issues.add(MAX_LEAVES_EXCEEDED)
    return leaves


def _evaluate_node(expr: Mapping[str, Any], sets: Mapping[str, frozenset[str]]) -> tuple[frozenset[str], set[str]]:
    node_type = expr["type"]

    if node_type == "condition":
        return sets.get(expr["conditionId"], frozenset()), set()

    if node_type == "and":
        child_results = [_evaluate_node(child, sets) for child in expr["children"]]
        codes = child_results[0][0]
        excluded: set[str] = set()
        for child_codes, child_excluded in child_results[1:]:
            codes = codes & child_codes
            excluded.update(child_excluded)
        excluded.update(child_results[0][1])
        return codes, excluded

    if node_type == "or":
        codes = frozenset[str]()
        excluded: set[str] = set()
        for child in expr["children"]:
            child_codes, child_excluded = _evaluate_node(child, sets)
            codes = codes | child_codes
            excluded.update(child_excluded)
        return codes, excluded

    base_codes, excluded = _evaluate_node(expr["base"], sets)
    subtract_union = frozenset[str]()
    for child in expr["subtract"]:
        child_codes, child_excluded = _evaluate_node(child, sets)
        subtract_union = subtract_union | child_codes
        excluded.update(child_excluded)
    excluded.update(base_codes & subtract_union)
    return base_codes - subtract_union, excluded
