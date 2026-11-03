"""Server-recorded user edits are provenance, never automatic semantic approval."""
import hashlib
import json

from fastapi import HTTPException
from sqlalchemy import select

from casepilot_api.models import WorkspaceTestBrief

KEY = "_user_source_hashes"
LIST_FIELDS = ("business_rules", "constraints", "scope", "roles", "core_flows")


def digest(value):
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def values(content):
    result = {json.dumps(["field", "test_objective"]): content.get("test_objective", "")}
    for field in LIST_FIELDS:
        for text in content.get(field, []) or []:
            if isinstance(text, str) and text.strip():
                result[json.dumps(["list", field, digest(text)])] = text
    plan = content.get("planning") or {}
    if not isinstance(plan, dict):
        plan = {}
    for group, fields in (("test_points", ("scenario", "objective")),
                          ("feature_points", ("description",))):
        for item in plan.get(group, []) or []:
            if isinstance(item, dict) and isinstance(item.get("id"), str):
                for field in fields:
                    value = item.get(field, "")
                    if isinstance(value, str):
                        result[json.dumps([group, item["id"], field])] = value
    return result


def capture_user_edits(previous, current, version):
    old, new = values(previous or {}), values(current)
    changed = {
        key: {"value_hash": digest(new.get(key)), "version": version,
              "object_hash": digest(str(current.get("test_object", "")).strip())}
        for key in old.keys() | new.keys() if old.get(key) != new.get(key)
    }
    if len(changed) > 4096:
        raise HTTPException(409, "test_brief_user_source_limit")
    return changed


def resolve_user_sources(records, content):
    """Latest edit wins, including deletions; copied metadata is not a new edit."""
    scope = str(content.get("test_object", "")).strip()
    if not scope:
        return []
    latest = {}
    for version, stored in records:
        markers = stored.get(KEY)
        if not isinstance(markers, dict):
            continue
        supplied = values(stored)
        for key, record in markers.items():
            if (isinstance(record, dict) and type(record.get("version")) is int
                    and record["version"] == version
                    and record.get("object_hash") == digest(scope)):
                latest[key] = (record, supplied.get(key))
    plan = content.get("planning") or {}
    if not isinstance(plan, dict):
        plan = {}
    points = {p.get("id") for p in (plan.get("test_points") or []) if isinstance(p, dict)}
    features = {p.get("id") for p in (plan.get("feature_points") or []) if isinstance(p, dict)}
    output, seen = [], set()
    for key, (record, text) in latest.items():
        if (not isinstance(text, str) or not text.strip()
                or record.get("value_hash") != digest(text)):
            continue
        path = json.loads(key)
        point_id = path[1] if path[0] == "test_points" else None
        feature_id = path[1] if path[0] == "feature_points" else None
        if (point_id and point_id not in points) or (feature_id and feature_id not in features):
            continue
        identity = (text, point_id, feature_id)
        if identity in seen:
            continue
        seen.add(identity)
        output.append({"text": text, "point_id": point_id, "feature_id": feature_id,
                       "source_version": record["version"]})
    if len(output) > 512 or sum(len(item["text"]) for item in output) > 100_000:
        raise HTTPException(409, "test_brief_user_source_limit")
    return output


def user_sources_for_brief(db, conversation, brief):
    if brief.conversation_id != conversation.id:
        raise HTTPException(409, "test_brief_source_changed")
    history = db.scalars(select(WorkspaceTestBrief).where(
        WorkspaceTestBrief.conversation_id == conversation.id,
        WorkspaceTestBrief.version <= brief.version,
    ).order_by(WorkspaceTestBrief.version))
    return resolve_user_sources([(row.version, row.content) for row in history], brief.content)
