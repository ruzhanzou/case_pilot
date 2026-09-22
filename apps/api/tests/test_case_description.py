from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from casepilot_api import case_management
from casepilot_api.schemas import TestCaseCreate as CreateSchema
from casepilot_api.schemas import TestCaseUpdate as UpdateSchema


def payload():
    return {"title": "Login", "steps": [{"action": "Submit", "expected": "Success"}]}


def test_description_is_optional_and_bounded():
    assert CreateSchema.model_validate(payload()).description == ""
    described = CreateSchema.model_validate({**payload(), "description": "Details"})
    assert described.description == "Details"
    with pytest.raises(ValidationError):
        CreateSchema.model_validate({**payload(), "description": "x" * 4001})


@pytest.mark.parametrize("fields, expected", [
    ({}, "Original description"),
    ({"description": None}, "Original description"),
    ({"description": ""}, ""),
    ({"description": " Updated description "}, "Updated description"),
])
def test_revision_preserves_omitted_description_and_allows_clearing(monkeypatch, fields, expected):
    revision_id = uuid4()
    case = SimpleNamespace(id=uuid4(), space_id=uuid4(), current_revision_id=revision_id)
    current = SimpleNamespace(
        description="Original description", source_refs=[], execution_level="L0",
        test_domains=[], automation_type="manual", automation_cases=[],
    )
    db = Mock()
    db.scalar.side_effect = [current, 1]
    monkeypatch.setattr(case_management, "ensure_case", lambda *args: case)
    monkeypatch.setattr(case_management, "write_audit", lambda *args, **kwargs: None)
    monkeypatch.setattr(case_management, "case_to_view", lambda *args: None)
    request = UpdateSchema.model_validate({**payload(), "base_revision_id": revision_id, **fields})
    case_management.update_test_case(case.id, request, SimpleNamespace(id=uuid4()), db)
    assert db.add.call_args.args[0].description == expected
    db.commit.assert_called_once()
