"""Exact review tokens for artifacts without a database revision timestamp."""
import hashlib
import json


def change_set_version(change):
    """Bind the artifact identity, review state, diff, and all item base versions."""
    content = {"id": str(change.id), "status": change.status, "items": change.items}
    return hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":"), default=str).encode()).hexdigest()


def operation_review_version(operation):
    """Bind the exact draft/target, excluding execution lifecycle pointers."""
    content = {"id": str(operation.id), "intent": operation.intent,
               "target": operation.target, "payload": operation.payload}
    return hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":"), default=str).encode()).hexdigest()
