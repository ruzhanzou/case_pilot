from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4
import pytest
from fastapi import HTTPException
from casepilot_api.conversations import _validate_reuse_source

@pytest.mark.parametrize('invalid', [None,'missing','version','checksum','expired','owner','object','not_ready'])
def test_excel_confirmation_checks_immutable_owned_document(invalid):
    account=SimpleNamespace(id=uuid4());conversation=SimpleNamespace(space_id=uuid4())
    doc=SimpleNamespace(status='ready',version=2,checksum='known',expires_at=None)
    origin=SimpleNamespace(status='ready',persistence='temporary',account_id=account.id)
    source={'kind':'excel','test_object_match':'same','document_id':str(uuid4()),'document_version':2,'document_checksum':'known'}
    if invalid=='version':source['document_version']=1
    if invalid=='checksum':source['document_checksum']='old'
    if invalid=='expired':doc.expires_at=datetime.now(UTC)-timedelta(seconds=1)
    if invalid=='owner':origin.account_id=uuid4()
    if invalid=='object':source['test_object_match']='unknown'
    if invalid=='not_ready':doc.status='processing'
    db=Mock();db.execute.return_value.first.return_value=None if invalid=='missing' else (doc,origin)
    if invalid:
        with pytest.raises(HTTPException) as error:_validate_reuse_source(db,conversation,account,source)
        assert error.value.status_code==409
    else:_validate_reuse_source(db,conversation,account,source)
