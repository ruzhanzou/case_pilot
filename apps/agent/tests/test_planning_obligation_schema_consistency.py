"""Synthetic schema/runtime comparisons; never reconstruction of live output."""
from copy import deepcopy

import pytest
from pydantic import ValidationError
from test_planning_boundary_flow import run

from casepilot_agent.planning_coverage import COVERAGE_INSTRUCTION


def probe(change):
    captured = {}

    def inspect(schema):
        captured['schema'] = schema

    def mutate(data, payload):
        data['test_points'][0].pop('boundary_samples')
        item = data['coverage_obligations'][0]
        item['point_ids'] = []
        change(item)
        captured['data'] = deepcopy(data)

    return captured, lambda: run(target=1, mutate=mutate, inspect_schema=inspect)


def assert_boundary_schema_requires_contract(captured):
    definitions = captured['schema']['$defs']
    boundary = definitions['BatchBoundaryObligation']
    ordinary = definitions['BatchOrdinaryObligation']
    assert boundary['properties']['dimension']['const'] == 'boundary'
    assert 'boundary_contract' in boundary['required']
    assert ordinary['properties']['dimension']['enum'] == ['normal', 'exception', 'state']
    return definitions


def test_missing_boundary_contract_is_rejected_by_schema_and_runtime():
    captured, execute = probe(lambda item: item.pop('boundary_contract'))
    with pytest.raises(ValidationError) as error:
        execute()
    errors = error.value.errors(include_input=False, include_context=False, include_url=False)
    assert any(e['type'] == 'missing' and e['loc'][-1] == 'boundary_contract' for e in errors)
    # Ordinary branch rejects dimension=boundary in the same union parse.
    assert any(e['type'] == 'literal_error' and e['loc'][-1] == 'dimension' for e in errors)
    assert_boundary_schema_requires_contract(captured)


def test_explicit_unresolved_is_schema_valid_and_remains_unverified():
    captured, execute = probe(lambda item: item.update(
        boundary_contract={'status': 'unresolved', 'reason': 'Missing semantics'}))
    result, calls = execute()
    definitions = assert_boundary_schema_requires_contract(captured)
    properties = definitions['BatchBoundaryObligation']['properties']
    alternatives = properties['boundary_contract']['anyOf']
    assert {'$ref': '#/$defs/UnresolvedBoundaryContract'} in alternatives
    unresolved = definitions['UnresolvedBoundaryContract']
    assert unresolved['properties']['status']['const'] == 'unresolved'
    assert 'reason' in unresolved['required']
    assert len(calls) == 1
    batch = result['coverage_review']['batches'][0]
    assert batch['clarifications']
    assert batch['obligations'][0]['point_ids'] == []
    assert 'coverage_unverified' in batch['warnings']
    assert result['test_points'][0].get('boundary_samples') in (None, [])


def test_legacy_clarification_is_runtime_only_cache_compatibility():
    def change(item):
        item.pop('boundary_contract')
        item['clarification'] = 'Missing semantics'

    captured, execute = probe(change)
    result, _ = execute()
    assert_boundary_schema_requires_contract(captured)
    assert result['coverage_review']['batches'][0]['clarifications']
    # Runtime compatibility is more permissive here; it is not a model schema
    # accepting the live-shaped missing-contract failure.


def test_prompt_does_not_offer_cache_only_form_as_model_output():
    assert '也可直接填写 clarification 并保持 point_ids 为空' not in COVERAGE_INSTRUCTION
    assert 'boundary 义务必须显式输出 boundary_contract' in COVERAGE_INSTRUCTION
