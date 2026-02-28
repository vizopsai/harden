import json
from pathlib import Path

from click.testing import CliRunner

from harden.cli import main
from harden.analyzer import dependencies as depmod
from harden.analyzer.models import AppAnalysis, FrameworkInfo
from harden.generators import generate_dockerfile, generate_sbom
from harden import locker


def test_osv_cache_is_used(tmp_path, monkeypatch):
    (tmp_path / "requirements.txt").write_text("requests==2.30.0\n", encoding="utf-8")

    calls = {"count": 0}

    def fake_query(packages):
        calls["count"] += 1
        return {
            "requests@2.30.0": [
                {"id": "CVE-TEST-1", "severity": "CRITICAL", "summary": "test vuln"}
            ]
        }

    monkeypatch.setattr(depmod, "_query_osv_batch", fake_query)

    deps = depmod.analyze_dependencies(str(tmp_path))
    req = next(d for d in deps if d.name == "requests")
    assert req.has_known_cves is True
    assert any("CVE-TEST-1" in item for item in req.cve_details)

    cache_path = tmp_path / ".harden" / "state" / "osv_cache.json"
    assert cache_path.exists()
    assert calls["count"] == 1

    # Second run should use cache and avoid querying OSV
    def fail_query(_packages):
        raise AssertionError("OSV query should have used cache")

    monkeypatch.setattr(depmod, "_query_osv_batch", fail_query)
    deps2 = depmod.analyze_dependencies(str(tmp_path))
    req2 = next(d for d in deps2 if d.name == "requests")
    assert req2.has_known_cves is True


def test_bare_imports_infer_lock_and_analyze(tmp_path, monkeypatch):
    (tmp_path / "app.py").write_text("import requests\n", encoding="utf-8")

    def fake_lock(project_path, source_file, lock_file, python_version):
        content = Path(source_file).read_text(encoding="utf-8")
        assert "requests" in content
        Path(lock_file).write_text("requests==2.31.0\n", encoding="utf-8")
        return locker.LockResult(
            lock_file=lock_file,
            strategy_used="uv",
            package_count=1,
            source_file=source_file,
        )

    monkeypatch.setattr(locker, "_lock_with_uv", fake_lock)

    result = locker.lock_dependencies(str(tmp_path), strategy="uv")
    assert Path(result.lock_file).exists()

    # Analyze should infer dependencies from imports when no manifest exists
    monkeypatch.setattr(depmod, "_query_osv_batch", lambda _packages: {})
    deps = depmod.analyze_dependencies(str(tmp_path))
    assert any(d.name == "requests" for d in deps)


def test_dockerfile_prefers_lockfile(tmp_path):
    (tmp_path / "requirements.lock").write_text("requests==2.31.0\n", encoding="utf-8")
    (tmp_path / "requirements.txt").write_text("requests\n", encoding="utf-8")

    analysis = AppAnalysis(
        project_path=str(tmp_path),
        framework=FrameworkInfo(name="fastapi", entry_point="app.py"),
    )
    dockerfile = generate_dockerfile(analysis)
    assert "requirements.lock" in dockerfile
    assert "pip install --no-cache-dir -r requirements.lock" in dockerfile


def test_dockerfile_pyproject_only(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='demo'\nversion='0.1.0'\n", encoding="utf-8"
    )
    analysis = AppAnalysis(
        project_path=str(tmp_path),
        framework=FrameworkInfo(name="script", entry_point="app.py"),
    )
    dockerfile = generate_dockerfile(analysis)
    assert "pyproject.toml" in dockerfile
    assert "pip install --no-cache-dir ." in dockerfile


def test_sbom_uses_lockfile(tmp_path, monkeypatch):
    (tmp_path / "requirements.lock").write_text("requests==2.31.0\n", encoding="utf-8")
    monkeypatch.setattr(depmod, "_query_osv_batch", lambda _packages: {})

    analysis = AppAnalysis(project_path=str(tmp_path))
    sbom_json = generate_sbom(analysis)
    data = json.loads(sbom_json)
    comp = next(c for c in data["components"] if c["name"] == "requests")
    assert comp["version"] == "2.31.0"


def test_generate_fails_on_critical(tmp_path, monkeypatch):
    (tmp_path / "requirements.lock").write_text("requests==2.30.0\n", encoding="utf-8")
    (tmp_path / "app.py").write_text("print('hi')\n", encoding="utf-8")

    def fake_query(_packages):
        return {
            "requests@2.30.0": [
                {"id": "CVE-TEST-CRIT", "severity": "CRITICAL", "summary": "boom"}
            ]
        }

    monkeypatch.setattr(depmod, "_query_osv_batch", fake_query)

    runner = CliRunner()
    result = runner.invoke(main, ["generate", str(tmp_path), "--fail-on-critical"])
    assert result.exit_code != 0
    assert "critical" in result.output.lower()
