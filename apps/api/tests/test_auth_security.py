import pytest
from pydantic import ValidationError

from casepilot_api.auth import hash_password, normalize_email, verify_password
from casepilot_api.config import Settings


def test_password_hash_round_trip() -> None:
    encoded = hash_password("CasePilot123!")

    assert encoded != "CasePilot123!"
    assert verify_password("CasePilot123!", encoded)
    assert not verify_password("wrong-password", encoded)


def test_email_is_normalized() -> None:
    assert normalize_email(" Demo@CasePilot.Local ") == "demo@casepilot.local"


def test_production_rejects_demo_account_seeding() -> None:
    with pytest.raises(ValidationError, match="CASEPILOT_SEED_DEMO_DATA"):
        Settings(
            _env_file=None,
            CASEPILOT_ENV="production",
            CASEPILOT_SEED_DEMO_DATA=True,
        )
