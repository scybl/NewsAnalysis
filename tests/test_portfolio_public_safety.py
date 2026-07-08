from pathlib import Path

from scripts.verify_portfolio_public import scan


ROOT = Path(__file__).resolve().parents[1]
PORTFOLIO = ROOT / "portfolio_public"


def test_portfolio_public_safety_scan_passes():
    assert scan(PORTFOLIO) == []


def test_portfolio_public_contains_no_python_or_deployment_sources():
    forbidden_suffixes = {".py", ".sh", ".yml", ".yaml", ".toml"}
    files = [path.relative_to(PORTFOLIO) for path in PORTFOLIO.rglob("*") if path.is_file()]

    assert files
    assert not [path for path in files if path.suffix in forbidden_suffixes]
    assert not [path for path in files if path.name in {"Dockerfile", ".env", ".deploy.env"}]


def test_portfolio_public_documents_private_source_boundary():
    readme = (PORTFOLIO / "README.md").read_text(encoding="utf-8")
    security = (PORTFOLIO / "SECURITY.md").read_text(encoding="utf-8")
    readme_lower = readme.lower()

    assert "production source code is intentionally not included" in readme_lower
    assert "must never contain production secrets" in security
    assert "real crawler implementations" in readme_lower
