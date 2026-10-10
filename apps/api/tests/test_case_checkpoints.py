import pytest
from pydantic import ValidationError
from casepilot_api.schemas import TestCaseCreate

def test_case_checkpoints_need_not_match_each_procedure():
    case = TestCaseCreate(title='Login', steps=[{'action':'Open','expected':'Session exists'}, {'action':'Submit','expected':''}])
    assert len(case.steps) == 2
    assert case.steps[1].expected == ''

@pytest.mark.parametrize('rows', [[{'action':'Open','expected':''}], [{'action':'','expected':'Session exists'}]])
def test_case_requires_both_procedure_and_checkpoints(rows):
    with pytest.raises(ValidationError):
        TestCaseCreate(title='Login', steps=rows)
