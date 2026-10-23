"""Keep a message's effects and replay receipt in one database transaction."""
import logging
from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session


class SubmissionTransaction:
    """Nested action handlers may flush, but only the request owner commits."""

    def __init__(self, session: Session):
        self.session = session
        self.effects: list[Callable[[], Any]] = []

    def __getattr__(self, name: str):
        return getattr(self.session, name)

    def commit(self):
        self.session.flush()

    def publish_committed_effects(self):
        for effect in self.effects:
            try:
                effect()
            except Exception:
                # The committed database state remains authoritative; job polling
                # and worker cancellation guards recover transient broker errors.
                logging.getLogger(__name__).warning('submission_notification_failed', exc_info=True)


def after_commit(db, effect: Callable[[], Any]):
    if isinstance(db, SubmissionTransaction):
        db.effects.append(effect)
    else:
        effect()
