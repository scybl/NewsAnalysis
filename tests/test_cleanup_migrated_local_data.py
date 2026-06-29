import sys

from scripts import cleanup_migrated_local_data


def test_cleanup_migrated_local_data_dry_run_keeps_files(monkeypatch, tmp_path, capsys):
    local_data = tmp_path / "local_data"
    migrated_stock = local_data / "000001.SZ"
    missing_stock = local_data / "000002.SZ"
    temp_stock = local_data / ".000003.SZ.tmp_20260628_120000"
    kaipanla = local_data / "kaipanla"
    mongo = local_data / "mongo"
    secure = local_data / "secure"
    for path in (migrated_stock, missing_stock, temp_stock, kaipanla, mongo, secure):
        path.mkdir(parents=True)
        (path / "keep.txt").write_text("x", encoding="utf-8")

    monkeypatch.setattr(cleanup_migrated_local_data, "LOCAL_DATA_DIR", local_data)
    monkeypatch.setattr(cleanup_migrated_local_data, "KAIPANLA_DATA_DIR", kaipanla)
    monkeypatch.setattr(cleanup_migrated_local_data, "list_mongo_stock_codes", lambda: ["000001.SZ"])
    monkeypatch.setattr(sys, "argv", ["cleanup_migrated_local_data.py"])

    assert cleanup_migrated_local_data.main() == 1
    payload = capsys.readouterr().out

    assert '"stock_package_dir"' in payload
    assert '"stale_stock_temp_dir"' in payload
    assert '"legacy_kaipanla_dir"' in payload
    assert migrated_stock.exists()
    assert missing_stock.exists()
    assert temp_stock.exists()
    assert kaipanla.exists()
    assert mongo.exists()
    assert secure.exists()


def test_cleanup_migrated_local_data_apply_deletes_only_verified_business_dirs(monkeypatch, tmp_path):
    local_data = tmp_path / "local_data"
    migrated_stock = local_data / "000001.SZ"
    missing_stock = local_data / "000002.SZ"
    temp_stock = local_data / ".000003.SZ.tmp_20260628_120000"
    kaipanla = local_data / "kaipanla"
    mongo = local_data / "mongo"
    secure = local_data / "secure"
    for path in (migrated_stock, missing_stock, temp_stock, kaipanla, mongo, secure):
        path.mkdir(parents=True)
        (path / "keep.txt").write_text("x", encoding="utf-8")

    monkeypatch.setattr(cleanup_migrated_local_data, "LOCAL_DATA_DIR", local_data)
    monkeypatch.setattr(cleanup_migrated_local_data, "KAIPANLA_DATA_DIR", kaipanla)
    monkeypatch.setattr(cleanup_migrated_local_data, "list_mongo_stock_codes", lambda: ["000001.SZ"])
    monkeypatch.setattr(sys, "argv", ["cleanup_migrated_local_data.py", "--apply"])

    assert cleanup_migrated_local_data.main() == 1

    assert not migrated_stock.exists()
    assert missing_stock.exists()
    assert not temp_stock.exists()
    assert not kaipanla.exists()
    assert mongo.exists()
    assert secure.exists()
