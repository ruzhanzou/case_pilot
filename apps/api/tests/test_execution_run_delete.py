from unittest.mock import Mock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from casepilot_api.case_management import delete_execution_run


@pytest.mark.parametrize("status", ["active", "completed", "aborted"])
def test_manager_can_delete_run_with_audit(status):
    db, account = Mock(), Mock(id=uuid4())
    run = Mock(id=uuid4(), space_id=uuid4(), status=status)
    db.get.return_value = run
    with (
        patch("casepilot_api.case_management.require_space_membership"),
        patch("casepilot_api.case_management.can_manage_execution_run", return_value=True),
        patch("casepilot_api.case_management.write_audit") as audit,
    ):
        assert delete_execution_run(run.id, account, db).status_code == 204
        db.delete.assert_called_once_with(run)
        db.commit.assert_called_once()
        assert audit.call_args.kwargs["action"] == "execution_run.deleted"


@pytest.mark.parametrize("missing,member,manager,expected", [
    (True, True, True, 404),
    (False, False, True, 403),
    (False, True, False, 403),
])
def test_delete_rejects_missing_and_unauthorized_runs(missing, member, manager, expected):
    db, account = Mock(), Mock(id=uuid4())
    db.get.return_value = None if missing else Mock(id=uuid4(), space_id=uuid4())
    with (
        patch("casepilot_api.case_management.require_space_membership",
              side_effect=None if member else HTTPException(403)),
        patch("casepilot_api.case_management.can_manage_execution_run", return_value=manager),
        pytest.raises(HTTPException) as caught,
    ):
        delete_execution_run(uuid4(), account, db)
    assert caught.value.status_code == expected
    db.delete.assert_not_called()
    db.commit.assert_not_called()
