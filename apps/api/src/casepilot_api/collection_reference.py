"""Shared semantic collection evidence and server-side boundary validation."""
from typing import Literal
from pydantic import BaseModel, Field


class CollectionReference(BaseModel):
    target_collection_id: str | None = Field(default=None, description=(
        "明确作为本次操作目标的用例集合ID。普通业务名称、测试对象、参考来源、"
        "否定切换以及要求继续当前集合时均为null。不能仅按名称重合选集合。"
    ))
    collection_reference: Literal["none", "current", "named"] = "none"
    target_collection_evidence: str = Field(default="", description=(
        "仅named时填写：用户本轮明确指定目标集合的连续原文片段。不得抄目录名称或改写原话。"
    ))


collection_instructions = (
    "target_collection_id仅返回用户指向的目标用例集合ID，来自collection_catalog；"
    "没有明确指向、多个集合或只是提到同名业务时返回null。"
    "explicit_collection_only为true时，必须明确将该名称当作集合，普通测试对象名称不算。"
    "current_collection_id是当前对话绑定的集合。当前集合/这个集合是collection_reference=current，target_collection_id=null。"
    "例如查询当前集合的登录用例，即使目录有账号登录验收用例集，也不得改指那个集合。"
    "明确指定其他目标集合才是named，并填写target_collection_evidence为用户本轮连续原文；没有目标集合引用是none。"
    "参考来源集合不是要切换的目标集合；否定切换、引用示例也不是目标。"
    "例如目录有订单集合，用户说为订单业务增加用例，继续维护当前集合，"
    "target_collection_id必须是null；只有说在订单集合操作才选对应ID。"
)


def validate_collection_reference(reference, content: str, catalog: list[dict], current_id: str | None):
    target = reference.target_collection_id
    if target is not None and target not in {item["id"] for item in catalog}:
        raise ValueError("collection_reference_outside_catalog")
    if current_id and target:
        if reference.collection_reference == "current" or target == current_id:
            return None
        if (reference.collection_reference != "named" or not reference.target_collection_evidence.strip()
                or reference.target_collection_evidence not in content):
            raise ValueError("collection_reference_without_user_evidence")
    return target
