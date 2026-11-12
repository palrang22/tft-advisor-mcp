"""`docs/ARCHITECTURE.md` 의존성 규칙 검사. 모듈별 import를 읽어 금지 항목이 있으면 실패한다."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

WEB = ("mcp", "fastapi", "starlette")
BIGQUERY = ("google.cloud.bigquery",)
BQ_REPO = "core/repo/bq_repo.py"


@dataclass(frozen=True)
class Rule:
    package: str
    forbidden: tuple[str, ...]
    exempt: tuple[str, ...] = ()


RULES = (
    Rule("adapters", ("static", "snapshot")),
    Rule("core", WEB),
    Rule("core", BIGQUERY, exempt=(BQ_REPO,)),
    Rule("static", ("core.advisor", "core.calc", "adapters")),
    Rule("snapshot", ("core.advisor", "core.calc", "adapters")),
)


def module_name(path: Path) -> str:
    parts = path.relative_to(ROOT).with_suffix("").parts
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def imported_modules(source: str, module: str, is_package: bool) -> set[str]:
    """소스의 import를 절대 모듈 이름으로 모은다.

    `from a import b`는 `a`와 `a.b`를 모두 넣는다 (`b`가 하위 모듈일 수 있어서).
    상대 import는 `module` 기준으로 푼다.
    """
    found: set[str] = set()
    package_parts = module.split(".") if is_package else module.split(".")[:-1]
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                keep = len(package_parts) - (node.level - 1)
                base_parts = package_parts[: max(keep, 0)]
                if node.module:
                    base_parts = [*base_parts, node.module]
                base = ".".join(base_parts)
            else:
                base = node.module or ""
            if base:
                found.add(base)
            found.update(f"{base}.{a.name}" if base else a.name for a in node.names)
    return found


def matches(name: str, prefix: str) -> bool:
    return name == prefix or name.startswith(prefix + ".")


def violations(rule: Rule) -> list[str]:
    out: list[str] = []
    for path in sorted((ROOT / rule.package).rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        if rel in rule.exempt:
            continue
        imports = imported_modules(
            path.read_text(encoding="utf-8"), module_name(path), path.name == "__init__.py"
        )
        out.extend(
            f"{rel} imports {name}"
            for name in sorted(imports)
            for prefix in rule.forbidden
            if matches(name, prefix)
        )
    return out


@pytest.mark.parametrize("rule", RULES, ids=lambda r: f"{r.package}-x-{'|'.join(r.forbidden)}")
def test_layering(rule: Rule) -> None:
    assert (ROOT / rule.package).is_dir(), f"{rule.package}/ 디렉터리가 없다"
    assert violations(rule) == []


@pytest.mark.parametrize(
    ("source", "module", "is_package", "expected"),
    [
        ("from google.cloud import bigquery", "core.calc.x", False, "google.cloud.bigquery"),
        ("import google.cloud.bigquery as bq", "core.calc.x", False, "google.cloud.bigquery"),
        ("from core import advisor", "static.loader", False, "core.advisor"),
        ("from ..calc import odds", "core.advisor.find", False, "core.calc"),
        ("from .. import calc", "core.advisor", True, "core.calc"),
        ("from mcp.server.fastmcp import FastMCP", "core.registry", False, "mcp"),
    ],
)
def test_import_resolution_catches_forbidden(
    source: str, module: str, is_package: bool, expected: str
) -> None:
    imports = imported_modules(source, module, is_package)
    assert any(matches(name, expected) for name in imports)


def test_prefix_match_is_module_boundary() -> None:
    assert not matches("mcpx", "mcp")
    assert not matches("static_helpers", "static")
