from __future__ import annotations

import json
from pathlib import Path

import pytest

from kiwoom_worker.core.expr import (
    ConditionInfo,
    evaluate,
    leaf_condition_ids,
    validate_definition,
)

CASES = Path(__file__).parents[3] / "packages/contracts/cases"


def load(path: Path) -> list[dict[str, object]]:
    return json.loads(path.read_text(encoding="utf-8"))["cases"]


def cond(condition_id: str) -> dict[str, str]:
    return {"type": "condition", "conditionId": condition_id}


def and_(*children: dict[str, object]) -> dict[str, object]:
    return {"type": "and", "children": list(children)}


def or_(*children: dict[str, object]) -> dict[str, object]:
    return {"type": "or", "children": list(children)}


@pytest.mark.parametrize("case", load(CASES / "validate.json"), ids=lambda case: case["name"])
def test_validate_matches_contract(case: dict[str, object]) -> None:
    conditions = {
        condition_id: ConditionInfo(payload["profileId"], payload["active"])
        for condition_id, payload in case["conditions"].items()
    }

    assert validate_definition(case["definition"], conditions) == case["issues"]


@pytest.mark.parametrize("case", load(CASES / "evaluate.json"), ids=lambda case: case["name"])
def test_evaluate_matches_contract(case: dict[str, object]) -> None:
    result = evaluate(case["expr"], {condition_id: frozenset(values) for condition_id, values in case["sets"].items()})

    assert (result.codes, result.matches, result.excluded) == (
        case["expected"]["codes"],
        case["expected"]["matches"],
        case["expected"]["excluded"],
    )


def test_leaf_ids_dfs_unique() -> None:
    assert leaf_condition_ids(and_(cond("A"), or_(cond("B"), cond("A")))) == ["A", "B"]
