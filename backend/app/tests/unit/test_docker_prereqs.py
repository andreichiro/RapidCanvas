from __future__ import annotations

import importlib.util
import socket
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _load_script() -> Any:
    root = Path(__file__).resolve().parents[4]
    script_path = root / "scripts" / "check_docker_prereqs.py"
    spec = importlib.util.spec_from_file_location("check_docker_prereqs", script_path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@dataclass(frozen=True)
class FakeUsage:
    free: int


def test_docker_daemon_check_reports_runner_success() -> None:
    script = _load_script()

    def runner(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args=["docker"], returncode=0, stdout="25.0.0\n")

    result = script.check_docker_daemon(runner)

    assert result.ok is True
    assert "25.0.0" in result.message


def test_docker_daemon_check_reports_runner_failure() -> None:
    script = _load_script()

    def runner(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args=["docker"], returncode=1, stderr="daemon down")

    result = script.check_docker_daemon(runner)

    assert result.ok is False
    assert result.message == "daemon down"


def test_disk_space_check_requires_ten_gib() -> None:
    script = _load_script()

    result = script.check_disk_space(
        disk_usage=lambda _path: FakeUsage(free=script.MIN_FREE_BYTES - 1)
    )

    assert result.ok is False
    assert "need at least 10 GiB" in result.message


def test_port_available_detects_bound_port() -> None:
    script = _load_script()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        used_port = sock.getsockname()[1]

        assert script.port_available(used_port) is False


def test_render_results_marks_failures() -> None:
    script = _load_script()
    rendered = script.render_results(
        [
            script.CheckResult("docker_daemon", True, "ok"),
            script.CheckResult("ports_available", False, "Ports already in use: 8000"),
        ]
    )

    assert "ok docker_daemon: ok" in rendered
    assert "fail ports_available: Ports already in use: 8000" in rendered
