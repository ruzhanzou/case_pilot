from pathlib import Path
from shutil import copytree, rmtree


def main() -> None:
    workspace = Path(__file__).resolve().parents[1]
    source = workspace / "apps" / "agent" / "skills" / "test-case-generation"
    destination = Path.home() / ".codex" / "skills" / "casepilot-test-case-generation"
    if destination.is_symlink():
        raise RuntimeError("refusing_to_replace_skill_symlink")
    if destination.exists():
        rmtree(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    copytree(source, destination)
    print(destination)


if __name__ == "__main__":
    main()
