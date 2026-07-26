from casepilot_api.auth import hash_password, normalize_email, verify_password


def test_password_hash_round_trip() -> None:
    encoded = hash_password("CasePilot123!")

    assert encoded != "CasePilot123!"
    assert verify_password("CasePilot123!", encoded)
    assert not verify_password("wrong-password", encoded)


def test_email_is_normalized() -> None:
    assert normalize_email(" Demo@CasePilot.Local ") == "demo@casepilot.local"
