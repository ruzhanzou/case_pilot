"""Human-labelled QA utterances: authorization never implies adoption."""
import json
from pathlib import Path
import pytest
from casepilot_api.generation_strategy import generation_strategy_from_text, asset_choice_from_text
CORPUS=json.loads((Path(__file__).resolve().parents[3]/'tests/acceptance/natural_language_workbench.json').read_text())
@pytest.mark.parametrize('case',CORPUS['strategy_cases'],ids=lambda c:c['id'])
def test_strategy_authorization_corpus(case):
    assert generation_strategy_from_text(case['utterance']) == case['expected_strategy'], case['utterance']
@pytest.mark.parametrize('case',CORPUS['choice_cases'],ids=lambda c:c['id'])
def test_confirmation_never_guesses_scope(case):
    assert asset_choice_from_text(case['utterance'],case['displayed_asset_ids']) == case['expected_selection']
