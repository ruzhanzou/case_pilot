from datetime import UTC, datetime
from uuid import uuid4

from casepilot_api.case_management import matches_case_search, matches_collection_search
from casepilot_api.schemas import CaseCollectionView as CollectionView
from casepilot_api.schemas import TestCaseView as CaseView


def build_case() -> CaseView:
    return CaseView.model_validate(
        {
            "id": uuid4(),
            "case_key": "CP-42-CASE-001",
            "collection_ids": [uuid4()],
            "current_revision_id": uuid4(),
            "revision_number": 1,
            "title": "登录链路回归",
            "module": "认证中心",
            "priority": "P0",
            "case_type": "功能",
            "tags": ["smoke"],
            "preconditions": [],
            "steps": [{"id": "step-1", "action": "登录", "expected": "成功"}],
            "source": "需求生成",
            "creator": {
                "id": uuid4(),
                "display_name": "张三",
                "email": "zhangsan@example.com",
            },
            "test_targets": [
                {
                    "source_system": "testtool",
                    "target_type": "fr_test",
                    "target_id": 150079209,
                    "target_key": "FR-2026-042",
                    "title": "统一登录",
                    "linked_fr_ids": [150079209],
                    "linked_qpm_ids": ["QPM-88"],
                }
            ],
            "created_at": datetime.now(UTC),
        }
    )


def test_case_asset_search_matches_target_and_creator_fuzzily() -> None:
    test_case = build_case()

    assert matches_case_search(test_case, "fr_test")
    assert matches_case_search(test_case, "007920")
    assert matches_case_search(test_case, "fr-2026 张三")
    assert matches_case_search(test_case, "qpm-88 zhangsan")
    assert not matches_case_search(test_case, "FR-2026 李四")


def test_collection_search_matches_target_and_creator_fuzzily() -> None:
    collection = CollectionView.model_validate(
        {
            "id": uuid4(),
            "space_id": uuid4(),
            "name": "统一登录搜索验收",
            "description": "登录资产集合",
            "case_count": 2,
            "creator": {
                "id": uuid4(),
                "display_name": "李四",
                "email": "lisi@example.com",
            },
            "test_target": {
                "source_system": "testtool",
                "target_type": "fr_test",
                "target_id": 150079209,
                "target_key": "FR-2026-042",
                "title": "统一登录",
                "linked_fr_ids": [150079209],
                "linked_qpm_ids": ["QPM-88"],
            },
            "created_at": datetime.now(UTC),
        }
    )

    assert matches_collection_search(collection, "统一 登录")
    assert matches_collection_search(collection, "fr-2026 李四")
    assert matches_collection_search(collection, "007920 lisi")
    assert not matches_collection_search(collection, "fr-2026 张三")
