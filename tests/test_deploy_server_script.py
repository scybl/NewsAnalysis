from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_deploy_script_protects_long_running_jobs_and_fetch_tasks():
    script = (ROOT / "scripts" / "deploy_server.sh").read_text(encoding="utf-8")

    assert "DEPLOY_PROTECT_RUNNING_JOBS" in script
    assert "DEPLOY_FORCE_RESTART" in script
    assert "DEPLOY_SKIP_RESTART" in script
    assert "DEPLOY_BUILD_WHEN_PROTECTED" in script
    assert "DEPLOY_PROTECTED_TASK_STATUSES" in script
    assert "local_data/admin_tasks.json" in script
    assert "queued running stopping" in script
    assert "[admin tasks]" in script
    assert "minute-cold-worker" in script
    assert "news-crawler-guardian" in script
    assert '\\"news-crawler\\", \\"runs\\", \\"--limit\\", \\"20\\"' in script
    assert "active crawl_runs" in script
    assert "stock_pipeline market minute-cold" in script
    assert "bdpan .* upload" in script
    assert "re.search(protected_regex, line)" in script
    assert 'grep -E \\\\\\"$PROTECTED_REGEX' not in script
    assert "Protected long-running job detected" in script
    assert "docker compose -f docker-compose.prod.yml build" in script
    assert 'COMPOSE_UP_FLAGS="-d --build"' in script
    assert "docker compose -f docker-compose.prod.yml up ${COMPOSE_UP_FLAGS}" in script
    assert "Restart skipped by DEPLOY_SKIP_RESTART=1" in script
    assert "--force-recreate" in script
    assert "After the task finishes, run: qiangzhitongbu" in script


def test_compose_has_profiled_minute_cold_worker():
    compose = (ROOT / "docker-compose.prod.yml").read_text(encoding="utf-8")

    assert "minute-cold-worker:" in compose
    assert 'profiles: ["cold-worker"]' in compose
    assert 'command: ["sleep", "infinity"]' in compose
    assert "/home/ubuntu/.local/bin/bdpan:/usr/local/bin/bdpan:ro" in compose
    assert "/home/ubuntu/.config/bdpan:/root/.config/bdpan:ro" in compose


def test_local_sync_shortcuts_have_safe_and_force_modes():
    safe = (ROOT / "scripts" / "tongbu.sh").read_text(encoding="utf-8")
    force = (ROOT / "scripts" / "qiangzhitongbu.sh").read_text(encoding="utf-8")
    restart = (ROOT / "scripts" / "qiangzhichongqi.sh").read_text(encoding="utf-8")
    worker = (ROOT / "scripts" / "start_minute_cold_worker_upload.sh").read_text(encoding="utf-8")

    assert "DEPLOY_PROTECT_RUNNING_JOBS=\"${DEPLOY_PROTECT_RUNNING_JOBS:-1}\"" in safe
    assert "DEPLOY_FORCE_RESTART=0" in safe
    assert "DEPLOY_SKIP_RESTART=0" in safe
    assert "DEPLOY_PROTECT_RUNNING_JOBS=0" in force
    assert "DEPLOY_FORCE_RESTART=1" in force
    assert "DEPLOY_SKIP_RESTART=0" in force
    assert "DEPLOY_PROTECT_RUNNING_JOBS=0" in restart
    assert "DEPLOY_FORCE_RESTART=1" in restart
    assert "DEPLOY_SKIP_RESTART=0" in restart
    assert "--profile cold-worker up -d" in worker
    assert "minute-cold-worker" in worker
    assert "export-stock-year-upload" in worker
