from functools import lru_cache
from pathlib import Path


@lru_cache
def load_test_case_generation_skill() -> str:
    root = Path(__file__).resolve().parents[2] / "skills" / "test-case-generation"
    sections = [(root / "SKILL.md").read_text(encoding="utf-8")]
    for name in ("output-contract.md", "quality-gates.md"):
        sections.append((root / "references" / name).read_text(encoding="utf-8"))
    return "\n\n".join(sections)
