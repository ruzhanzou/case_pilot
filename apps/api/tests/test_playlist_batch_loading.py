from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import event

from casepilot_api.case_management import (
    case_to_view,
    cases_to_views,
    playlist_to_view,
    playlists_to_views,
    search_space_test_cases,
)
from casepilot_api.database import get_engine, get_session_factory
from casepilot_api.models import (
    Account,
    AuditEvent,
    CaseCollection,
    CaseProject,
    CollectionCaseMembership,
    Playlist,
    PlaylistCaseMembership,
    PlaylistSourceCollection,
    Space,
    SpaceMembership,
)
from casepilot_api.models import (
    TestCase as Case,
)
from casepilot_api.models import (
    TestCaseRevision as Revision,
)


def test_playlist_batches_preserve_case_metadata_and_bound_queries():
    # Transaction rollback keeps this performance fixture out of the workspace.
    with get_session_factory()() as db:
        account = Account(email=f"batch-{uuid4().hex}@casepilot.test",
                          display_name="Batch creator", password_hash="unused")
        space = Space(name="Batch test")
        db.add_all([account, space])
        db.flush()
        db.add(SpaceMembership(space_id=space.id, account_id=account.id, role="owner"))
        collection = CaseCollection(space_id=space.id, name=f'batch-{uuid4()}')
        db.add(collection)
        db.flush()
        db.add(CaseProject(space_id=space.id, account_id=account.id,
            collection_id=collection.id, public_id=uuid4().hex[:24],
            source_system="testtool", target_type="fr_test", target_id=150079209,
            target_key="FR-2026-042", title="统一登录", linked_fr_ids=[150079209],
            linked_qpm_ids=["QPM-88"], platform_link_expires_at=datetime.now(UTC)))
        cases = []
        for index in range(24):
            case = Case(space_id=space.id, case_key=f'BATCH-{uuid4().hex}')
            db.add(case)
            db.flush()
            revision = Revision(
                test_case_id=case.id, revision_number=1, title=f'Precisecase{index}',
                module='Batch', priority='P1', case_type='功能', tags=['batch'],
                preconditions=[], steps=[{'action': 'Open', 'expected': 'Ready'}],
                source_refs=[],
            )
            db.add(revision)
            db.flush()
            case.current_revision_id = revision.id
            db.add(CollectionCaseMembership(
                collection_id=collection.id, test_case_id=case.id, position=index,
            ))
            db.add(AuditEvent(
                space_id=space.id, actor_id=account.id, action='test_case.created',
                resource_type='test_case', resource_id=case.id,
            ))
            cases.append(case)
        playlists = []
        for index in range(8):
            playlist = Playlist(space_id=space.id, creator_id=account.id, name=f'Playlist {index}')
            db.add(playlist)
            db.flush()
            db.add(PlaylistSourceCollection(
                playlist_id=playlist.id, collection_id=collection.id, position=0,
            ))
            for position, case in enumerate(cases):
                db.add(PlaylistCaseMembership(
                    playlist_id=playlist.id, test_case_id=case.id, position=position,
                ))
            playlists.append(playlist)
        db.flush()
        expected_cases = [case_to_view(db, case) for case in cases]
        pages = [search_space_test_cases(space.id, account, db, limit=7, offset=offset)
                 for offset in range(0, 28, 7)]
        assert [item.id for page in pages for item in page] == [item.id for item in expected_cases]
        assert all(len(page) <= 7 for page in pages)
        assert search_space_test_cases(space.id, account, db, q="Precisecase23", limit=7) == [expected_cases[23]]
        assert len(search_space_test_cases(space.id, account, db, q=collection.name, limit=7)) == 7
        assert len(search_space_test_cases(space.id, account, db, q="Batch creator", limit=7)) == 7
        assert len(search_space_test_cases(space.id, account, db, q="qpm-88 creator", limit=7)) == 7
        assert len(search_space_test_cases(space.id, account, db, q="007920", limit=7)) == 7
        assert search_space_test_cases(space.id, account, db, q="%") == []
        assert len(search_space_test_cases(space.id, account, db, q="_")) == 24  # literal fr_test
        assert search_space_test_cases(space.id, account, db, q="fr%test") == []
        assert search_space_test_cases(space.id, account, db, q="nonexistent") == []
        assert search_space_test_cases(space.id, account, db, q="[]") == []
        assert search_space_test_cases(space.id, account, db, q='"') == []

        expected_playlists = [playlist_to_view(db, playlist) for playlist in playlists]
        statements = []

        def record(*args):
            statements.append(args[2])

        engine = get_engine()
        event.listen(engine, 'before_cursor_execute', record)
        try:
            assert cases_to_views(db, cases) == expected_cases
            assert len(statements) <= 5, len(statements)
            statements.clear()
            actual = playlists_to_views(db, playlists)
            assert len(statements) <= 9, len(statements)
            assert actual == expected_playlists
            assert [item.test_case for item in actual[0].cases] == expected_cases
            assert actual[0].source_collection_names == [collection.name]
            assert cases_to_views(db, []) == []
            assert playlists_to_views(db, []) == []
        finally:
            event.remove(engine, 'before_cursor_execute', record)
            db.rollback()
