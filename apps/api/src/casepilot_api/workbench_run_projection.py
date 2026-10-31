"""Read-only durable progress; polling is never a continuation trigger."""
from uuid import UUID

from sqlalchemy import case, select

from casepilot_api.models import WorkbenchRun
from casepilot_api.workbench_continuation import TERMINAL, project_run


def project_durable_state(db, conversation, state, *, latest=False):
    state = dict(state or {})
    statement = select(WorkbenchRun).where(
        WorkbenchRun.conversation_id == conversation.id,
        WorkbenchRun.account_id == conversation.account_id,
        WorkbenchRun.space_id == conversation.space_id,
    )
    if not latest:
        identifier = (state.get("durable_run") or {}).get("id")
        if not identifier:
            return state
        try:
            identifier = UUID(str(identifier))
        except (ValueError, TypeError):
            return {key: value for key, value in state.items() if key != "durable_run"}
        statement = statement.where(WorkbenchRun.id == identifier)
    ordering = ([case((WorkbenchRun.status.not_in(TERMINAL), 0), else_=1)]
                if latest else [])
    run = db.scalar(statement.order_by(
        *ordering, WorkbenchRun.created_at.desc(), WorkbenchRun.id.desc(),
    ).limit(1).execution_options(populate_existing=True))
    if run is None:
        return {key: value for key, value in state.items() if key != "durable_run"}
    return {**state, "durable_run": project_run(run)}
