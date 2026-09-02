from pathlib import Path

from casepilot_agent.skills import load_test_case_generation_skill


def test_runtime_loads_the_repository_skill_as_its_single_source() -> None:
    loaded = load_test_case_generation_skill()
    skill_path = (
        Path(__file__).resolve().parents[1]
        / "skills"
        / "test-case-generation"
        / "SKILL.md"
    )

    assert skill_path.read_text(encoding="utf-8") in loaded
    assert "untrusted evidence" in loaded
    assert "candidate" in loaded
