from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from zipfile import ZipFile


def test_wheel_includes_dashboard_static_assets(tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[1]
    wheel_directory = tmp_path / "wheel"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "--wheel-dir",
            str(wheel_directory),
            str(repository),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    wheel = next(wheel_directory.glob("smart_parking-*.whl"))

    with ZipFile(wheel) as archive:
        members = set(archive.namelist())

    assert {
        "backend/app/static/dashboard.html",
        "backend/app/static/dashboard.css",
        "backend/app/static/dashboard.js",
    } <= members
