"""Offline lookup contracts, not a claim of live model semantic understanding."""
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from casepilot_api import workbench_sources
from casepilot_api.workbench_tools import INSTRUCTIONS, AssetQueryArguments, WorkbenchTools


@pytest.mark.parametrize("search,mode", [
    ("", "catalog"), ("不存在_标题%", "title_literal_substring"),
])
def test_query_mode_is_explicit_and_no_match_never_mutates_or_broadens(search, mode, monkeypatch):
    conversation = SimpleNamespace(id=uuid4(), space_id=uuid4(), collection_id=uuid4(),
                                   context={"workbench_selection": {"version": 4, "items": []}})
    before = deepcopy(conversation.context)
    calls = []

    def execute(query):
        compiled = query.compile(dialect=postgresql.dialect())
        calls.append(compiled)
        return []

    monkeypatch.setattr(workbench_sources, "authorize", lambda *args: None)
    source = workbench_sources.WorkbenchSources(
        SimpleNamespace(execute=execute), None, conversation,
    )
    result = source.query_assets(search=search, scope="current_collection")
    assert result["search_mode"] == mode
    assert result["returned_count"] == 0
    assert result["cases"] == []
    assert result["truncated"] is False and result["has_more"] is False
    assert conversation.context == before
    assert len(calls) == 1  # No implicit widened fallback query.
    assert conversation.collection_id in calls[0].params.values()
    if search:
        assert "ILIKE" in str(calls[0])
        assert any(isinstance(value, str) and "不存在" in value
                   and "/_" in value and "/%" in value for value in calls[0].params.values())


def test_lookup_strategy_contract_distinguishes_semantic_catalog_from_literal_filter():
    description = AssetQueryArguments.model_json_schema()["properties"]["search"]["description"]
    assert "Literal" in description and "not semantic search" in description
    assert "scope=\"selection\"" in INSTRUCTIONS
    assert "descriptions/steps" in INSTRUCTIONS
    assert "never relax the filter" in INSTRUCTIONS
    specs = {spec.name: spec for spec in WorkbenchTools(None, None, None, None).specs()}
    assert "literal TITLE substring" in specs["query_assets"].description
    assert specs["query_assets"].fulfilled_actions == ("CASE_QUERY",)
    assert specs["query_assets"].effect == "read"
