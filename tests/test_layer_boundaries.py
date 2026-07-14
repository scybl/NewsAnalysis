from pathlib import Path

from backend.paths import STATIC_DIR


ROOT = Path(__file__).resolve().parents[1]


def test_frontend_admin_assets_live_outside_python_package():
    assert (ROOT / "frontend" / "admin" / "admin.js").exists()
    assert (ROOT / "frontend" / "admin" / "styles.css").exists()
    assert not (ROOT / "stock_pipeline" / "web_static").exists()


def test_web_server_points_to_frontend_admin_static_dir():
    web = (ROOT / "stock_pipeline" / "web.py").read_text(encoding="utf-8")

    assert STATIC_DIR == ROOT / "frontend" / "admin"
    assert "from backend.paths import STATIC_DIR" in web
    assert 'Path(__file__).resolve().parent / "web_static"' not in web


def test_layer_documentation_exists_for_future_migrations():
    for path in (
        ROOT / "frontend" / "README.md",
        ROOT / "backend" / "README.md",
        ROOT / "datahub" / "README.md",
        ROOT / "docs" / "LAYER_BOUNDARIES.md",
    ):
        assert path.exists(), path
