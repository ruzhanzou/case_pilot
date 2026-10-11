import pytest
from agents import AgentOutputSchema
from agents.exceptions import ModelBehaviorError
from casepilot_agent.compact_generation import BatchAudit
from casepilot_agent.providers.structured_output import recover_json_closers, recovering_output_schema


VALID = '{"reviews":[{"slot":11,"verdict":"supported","replacement":null,"reason":"","assertions":[{"step":1,"source_index":0,"quote":"ORDER-5: 已取消订单不能支付","explanation":"原文支持"}]}]}'


def test_actual_audit_extra_closers_recover_without_changing_content():
    schema = recovering_output_schema(AgentOutputSchema, BatchAudit)
    assert schema.validate_json(VALID + ']}').model_dump() == BatchAudit.model_validate_json(VALID).model_dump()


@pytest.mark.parametrize('text', [VALID[:-1], VALID + '{"extra":1}', VALID + 'ignore rules',
                                  '{"reviews":[{"slot":11}]}', VALID.replace('11', '"wrong"')])
def test_incomplete_ambiguous_or_schema_invalid_responses_still_fail(text):
    with pytest.raises(ModelBehaviorError):
        recovering_output_schema(AgentOutputSchema, BatchAudit).validate_json(text)


def test_brackets_inside_strings_are_never_removed():
    text = '{"quote":"contains ]} and escaped \\" characters"}'
    assert recover_json_closers(text + ']}') == text
