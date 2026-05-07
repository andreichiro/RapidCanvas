"""Preflight checks for the local Docker Compose review stack."""

from __future__ import annotations

import shutil
import socket
import subprocess
import sys
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

ROOT = Path(__file__).resolve().parents[1]
MIN_FREE_BYTES = 10 * 1024 * 1024 * 1024
REQUIRED_PORTS = (5173, 8000, 6333, 5000)


class DiskUsage(Protocol):
    free: int


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    message: str


def check_docker_daemon(
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> CheckResult:
    """Verify Docker is installed and the daemon accepts commands."""

    try:
        result = runner(
            ["docker", "info", "--format", "{{.ServerVersion}}"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return CheckResult("docker_daemon", False, f"Docker is unavailable: {exc}")
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "docker info failed").strip()
        return CheckResult("docker_daemon", False, detail)
    version = (result.stdout or "unknown").strip()
    return CheckResult("docker_daemon", True, f"Docker daemon reachable ({version})")


def check_disk_space(
    path: Path = ROOT,
    disk_usage: Callable[[Path], DiskUsage] = shutil.disk_usage,
) -> CheckResult:
    """Verify the checkout volume has enough room for images and volumes."""

    free_bytes = int(disk_usage(path).free)
    free_gib = free_bytes / (1024 * 1024 * 1024)
    if free_bytes < MIN_FREE_BYTES:
        return CheckResult(
            "free_disk",
            False,
            f"Only {free_gib:.1f} GiB free; need at least 10 GiB",
        )
    return CheckResult("free_disk", True, f"{free_gib:.1f} GiB free")


def check_ports_available(
    ports: Iterable[int] = REQUIRED_PORTS,
    host: str = "127.0.0.1",
) -> CheckResult:
    """Verify Compose host ports are not already bound."""

    blocked = [port for port in ports if not port_available(port, host=host)]
    if blocked:
        ports_text = ", ".join(str(port) for port in blocked)
        return CheckResult("ports_available", False, f"Ports already in use: {ports_text}")
    ports_text = ", ".join(str(port) for port in ports)
    return CheckResult("ports_available", True, f"Ports available: {ports_text}")


def port_available(port: int, *, host: str = "127.0.0.1") -> bool:
    """Return whether a TCP port can be bound on the host."""

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def run_checks() -> list[CheckResult]:
    """Run all Docker preflight checks."""

    return [
        check_docker_daemon(),
        check_disk_space(),
        check_ports_available(),
    ]


def render_results(results: Sequence[CheckResult]) -> str:
    """Render concise human-readable preflight output."""

    return "\n".join(
        f"{'ok' if result.ok else 'fail'} {result.name}: {result.message}"
        for result in results
    )


def main() -> int:
    results = run_checks()
    print(render_results(results))
    return 0 if all(result.ok for result in results) else 1


if __name__ == "__main__":
    sys.exit(main())
