"""Lossless recovery for a complete JSON object followed by redundant closers."""
import json
import re


def recover_json_closers(content: str) -> str:
    normalized = content.strip()
    try:
        value, end = json.JSONDecoder().raw_decode(normalized)
    except ValueError:
        return content
    # Never repair inside the object or discard a second object/prose. Domain
    # schema and business validation remain mandatory after this normalization.
    if isinstance(value, dict) and re.fullmatch(r"[\s\]}]+", normalized[end:]):
        return normalized[:end]
    return content


def recovering_output_schema(schema_type, result_type):
    class RecoveringOutputSchema(schema_type):
        def validate_json(self, json_str):
            return super().validate_json(recover_json_closers(json_str))

    return RecoveringOutputSchema(result_type, strict_json_schema=False)
