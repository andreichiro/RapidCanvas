"""Validate local Codex project skills.

Usage:
    python3 scripts/quick_validate.py
    python3 scripts/quick_validate.py .codex/skills/rag-eval-mlflow
"""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SKILLS_ROOT = ROOT / ".codex" / "skills"
REQUIRED_AGENT_FIELDS = ("display_name", "short_description", "default_prompt")


class SkillValidationError(RuntimeError):
    """Raised when a project skill is malformed."""


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    paths = [Path(arg) for arg in args] if args else sorted(DEFAULT_SKILLS_ROOT.iterdir())
    skill_dirs = [path if path.is_absolute() else ROOT / path for path in paths]
    for skill_dir in skill_dirs:
        validate_skill(skill_dir)
        print(f"skill valid: {skill_dir.relative_to(ROOT)}")
    return 0


def validate_skill(skill_dir: Path) -> None:
    if not skill_dir.is_dir():
        raise SkillValidationError(f"{skill_dir} is not a skill directory")
    skill_md = skill_dir / "SKILL.md"
    agent_yaml = skill_dir / "agents" / "openai.yaml"
    references_dir = skill_dir / "references"
    _require_file(skill_md)
    _require_file(agent_yaml)
    if not references_dir.is_dir():
        raise SkillValidationError(f"{references_dir} is missing")
    references = sorted(references_dir.glob("*.md"))
    if not references:
        raise SkillValidationError(f"{references_dir} must contain at least one markdown reference")
    _validate_skill_markdown(skill_dir.name, skill_md)
    _validate_agent_yaml(agent_yaml)
    for reference in references:
        _require_nonempty(reference)


def _validate_skill_markdown(expected_name: str, path: Path) -> None:
    text = _require_nonempty(path)
    required_snippets = (
        "---",
        f"name: {expected_name}",
        "description:",
        "Workflow",
        "## Reference",
    )
    missing = [snippet for snippet in required_snippets if snippet not in text]
    if missing:
        raise SkillValidationError(f"{path} is missing required snippets: {', '.join(missing)}")


def _validate_agent_yaml(path: Path) -> None:
    text = _require_nonempty(path)
    if "interface:" not in text:
        raise SkillValidationError(f"{path} is missing interface block")
    missing = [field for field in REQUIRED_AGENT_FIELDS if f"{field}:" not in text]
    if missing:
        raise SkillValidationError(f"{path} is missing fields: {', '.join(missing)}")


def _require_file(path: Path) -> None:
    if not path.is_file():
        raise SkillValidationError(f"{path} is missing")


def _require_nonempty(path: Path) -> str:
    _require_file(path)
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise SkillValidationError(f"{path} is empty")
    return text


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SkillValidationError as exc:
        print(f"skill validation failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
