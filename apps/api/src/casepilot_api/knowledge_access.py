"""Temporary uploads belong to their uploader, even inside a shared space."""

from sqlalchemy import false, or_

from casepilot_api.models import KnowledgeSource


def source_access_filter(account_id):
    # Space membership is checked by each caller; this predicate never grants it.
    return or_(
        KnowledgeSource.persistence != "temporary",
        KnowledgeSource.account_id == account_id if account_id is not None else false(),
    )
