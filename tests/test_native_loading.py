"""独立进程验证 CLI 与 Python PTC 的配置发现和相对路径解析。"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("mode", ["cli", "ptc"])
def test_native_config_from_another_working_directory(tmp_path, mode):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    marker = config_dir / "imports.txt"
    (config_dir / "handlers.py").write_text(
        "from pathlib import Path\nfrom axi import tool\n"
        "with Path(__file__).with_name('imports.txt').open('a') as f: f.write('loaded\\n')\n"
        "@tool(name='ping')\ndef ping(value: str) -> str:\n    return 'hello ' + value\n"
    )
    config = config_dir / "axi.json"
    config.write_text(
        json.dumps({"nativeTools": [{"module": "./handlers.py", "name": "local"}]})
    )
    env = {
        "HOME": str(tmp_path),
        "AXI_CONFIG": str(config),
        "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
        "PATH": os.environ.get("PATH", ""),
    }
    if mode == "cli":
        args = [
            "-c",
            "from axi.cli import app; app()",
            "run",
            "local/ping",
            "--value",
            "world",
        ]
    else:
        args = [
            "-c",
            "from axi import tool; "
            "assert tool('local/ping')(value='world') == 'hello world'; "
            "assert tool('ping')(value='again') == 'hello again'",
        ]
    result = subprocess.run(
        [sys.executable, *args],
        cwd=elsewhere,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert marker.read_text().splitlines() == ["loaded"]
    if mode == "cli":
        assert json.loads(result.stdout) == {"status": "success", "data": "hello world"}
