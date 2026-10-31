"""Run the live Atlas contract lane: a real Atlas container, synthetic data, the real metadata-atlas plugin.

    python tools/check_metadata_atlas_live.py --atlas-source ../unnamed_tracking_metadata
    python tools/check_metadata_atlas_live.py --image atlas-live:local -k achievements

Needs Docker (Linux or Windows/macOS Docker Desktop), Python 3.11+ and the requirements-dev packages. The
container is started on a free 127.0.0.1 port with a freshly generated bootstrap token, so nothing here
carries a credential, and it is always removed afterwards. Unknown arguments are passed to pytest.
"""
from __future__ import annotations

import argparse
import os
import secrets
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LANE = ROOT / "tests" / "atlas_live"


def docker(*args: str, check: bool = True, **options) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], check=check, text=True, **options)


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def wait_healthy(url: str, container: str, seconds: int = 90) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url + "/api/v2/health", timeout=3) as response:
                if response.status == 200:
                    return
        except OSError:
            pass
        time.sleep(1)
    logs = docker("logs", "--tail", "80", container, check=False, capture_output=True)
    raise SystemExit(f"Atlas did not become healthy within {seconds}s:\n{logs.stdout}{logs.stderr}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--atlas-source", type=Path, help="an Atlas checkout to build the image from")
    source.add_argument("--image", help="an existing Atlas image (for example one you built earlier)")
    parser.add_argument("--tag", default="atlas-live:local", help="tag for the image built from --atlas-source")
    parser.add_argument("--keep", action="store_true", help="leave the container running afterwards")
    parser.add_argument("--log-dir", type=Path, help="write the container log and pytest output here")
    options, pytest_args = parser.parse_known_args()

    if subprocess.run(["docker", "info"], capture_output=True).returncode != 0:
        raise SystemExit("Docker is not reachable. Start Docker (Desktop) and retry; this lane has no mocked fallback.")
    image = options.image
    if options.atlas_source:
        docker("build", "-t", options.tag, str(options.atlas_source.resolve()))
        image = options.tag

    port = free_port()
    url = f"http://127.0.0.1:{port}"
    bootstrap = secrets.token_urlsafe(48)
    container = f"atlas-live-{os.getpid()}"
    docker("rm", "-f", container, check=False, capture_output=True)
    docker("run", "-d", "--name", container, "-p", f"127.0.0.1:{port}:8000",
           "-e", "ATLAS_ROLE=local", "-e", f"ATLAS_PUBLIC_URL={url}", "-e", "ATLAS_STEAM_ENABLED=false",
           "-e", f"ATLAS_BOOTSTRAP_ADMIN_TOKEN={bootstrap}", image, capture_output=True)
    status = 1
    try:
        wait_healthy(url, container)
        env = {**os.environ, "ATLAS_LIVE_URL": url, "ATLAS_LIVE_BOOTSTRAP_TOKEN": bootstrap,
               "ATLAS_LIVE_CONTAINER": container}
        command = [sys.executable, "-m", "pytest", str(LANE), "-ra", *pytest_args]
        print("+", " ".join(command[:5]), "...", flush=True)
        if options.log_dir:
            options.log_dir.mkdir(parents=True, exist_ok=True)
            with (options.log_dir / "pytest.log").open("w", encoding="utf-8") as log:
                run = subprocess.Popen(command, cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       text=True, encoding="utf-8", errors="replace")
                for line in run.stdout:
                    sys.stdout.write(line)
                    log.write(line)
                status = run.wait()
        else:
            status = subprocess.run(command, cwd=ROOT, env=env).returncode
    finally:
        if options.log_dir:
            options.log_dir.mkdir(parents=True, exist_ok=True)
            logs = docker("logs", container, check=False, capture_output=True)
            (options.log_dir / "atlas-container.log").write_text(logs.stdout + logs.stderr, encoding="utf-8")
        if not options.keep:
            docker("rm", "-f", container, check=False, capture_output=True)
        else:
            print(f"Container {container} left running at {url}")
    return status


if __name__ == "__main__":
    sys.exit(main())
