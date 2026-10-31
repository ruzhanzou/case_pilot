"""Short-lived PostgreSQL collection row token (proposals expire after 15 minutes)."""

from sqlalchemy import text


def collection_revision(db, collection_id):
    # Collections have no updated_at column. xmin detects rename-away-and-back;
    # it is a wrapping transaction ID, not a durable/global revision identifier.
    return "xmin:" + str(
        db.scalar(
            text("SELECT xmin::text FROM case_collections WHERE id = :id"),
            {"id": collection_id},
        )
    )
