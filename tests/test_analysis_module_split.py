from pathlib import Path

from stock_pipeline.config import get_settings
from stock_pipeline.web import ANALYSIS_MODULE_STATUS_TEXT, StockWebApp


ROOT = Path(__file__).resolve().parents[1]
ANALYSIS_ROOT = ROOT.parent / "Analysis"
STATIC = ROOT / "stock_pipeline" / "web_static"


def test_analysis_execution_is_external_by_default(monkeypatch):
    monkeypatch.delenv("STOCK_ANALYSIS_EXECUTION_ENABLED", raising=False)
    monkeypatch.delenv("STOCK_ANALYSIS_EXTERNAL_URL", raising=False)

    settings = get_settings()

    assert settings.stock_analysis_execution_enabled is False
    assert settings.stock_analysis_external_url == ""


def test_web_reports_analysis_module_as_external(monkeypatch):
    monkeypatch.delenv("STOCK_ANALYSIS_EXECUTION_ENABLED", raising=False)
    monkeypatch.delenv("STOCK_ANALYSIS_EXTERNAL_URL", raising=False)

    app = StockWebApp()
    status = app.analysis_module_status()

    assert status["available"] is False
    assert status["mode"] == "external"
    assert status["message"] == ANALYSIS_MODULE_STATUS_TEXT


def test_frontend_marks_analysis_entry_as_archived():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    script = (STATIC / "app.js").read_text(encoding="utf-8")

    assert "A 股多源数据资产平台" in html
    assert "分析模块已封存" in html
    assert "analysisModuleAvailable = false" in script
    assert "分析模块已拆分为外部项目" in script


def test_analysis_implementation_lives_in_separate_project():
    assert not (ROOT / "StockAnalysisModule").exists()
    assert (ANALYSIS_ROOT / "pyproject.toml").exists()
    assert (ANALYSIS_ROOT / "stock_analysis_module" / "agents" / "multi_agent.py").exists()

    bridge = (ROOT / "stock_pipeline" / "agents" / "multi_agent.py").read_text(encoding="utf-8")
    assert "import_analysis_module" in bridge
    assert len(bridge.splitlines()) < 20


def test_analysis_bridge_uses_external_project_path(monkeypatch):
    from stock_pipeline import analysis_bridge

    monkeypatch.delenv("STOCK_ANALYSIS_PROJECT_DIR", raising=False)

    assert analysis_bridge.analysis_project_dir() == ANALYSIS_ROOT
    assert analysis_bridge.analysis_project_available() is True


def test_stock_outputs_do_not_require_analysis_project(monkeypatch, tmp_path):
    from stock_pipeline import stock_storage

    monkeypatch.setattr(stock_storage, "LOCAL_DATA_DIR", tmp_path)
    monkeypatch.setattr(stock_storage, "build_all_analysis_dossiers", lambda dossier: (_ for _ in ()).throw(RuntimeError("missing analysis")))
    saved = {}

    def fake_save(ts_code, full_data, metadata, *, dossier=None, analysis_dossiers=None):
        saved["ts_code"] = ts_code
        saved["full_data"] = full_data
        saved["metadata"] = metadata
        saved["dossier"] = dossier
        saved["analysis_dossiers"] = analysis_dossiers
        return {"ok": True, "packages": 1, "metadata": 1, "dataset_rows": 1}

    monkeypatch.setattr(stock_storage, "_save_stock_package_safe", fake_save)

    full_data = {
        "ts_code": "000001.SZ",
        "datasets": {"stock_basic": [{"ts_code": "000001.SZ", "name": "平安银行"}]},
        "date_range": {"start_date": "20260101", "end_date": "20260102"},
        "fetch_errors": [],
    }

    stock_storage.ensure_current_layout("000001.SZ")
    stock_storage._write_stock_outputs("000001.SZ", full_data)

    current = stock_storage.current_dir("000001.SZ")
    assert not (current / "full_data.json").exists()
    assert saved["ts_code"] == "000001.SZ"
    assert saved["full_data"] == full_data
    assert saved["dossier"]
    assert saved["analysis_dossiers"] == {}
