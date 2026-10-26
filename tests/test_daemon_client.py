"""Daemon 客户端测试：连接错误处理和超时。"""

import pytest

from axi.config import DaemonConfig
from axi.daemon.client import _send
from axi.daemon.protocol import DaemonRequest


class TestRequestTimeout:
    """AXI_REQUEST_TIMEOUT 优先于 axi.json，落在 DaemonConfig 的 env 校验里。"""

    def test_env_overrides_config(self, monkeypatch):
        monkeypatch.setenv("AXI_REQUEST_TIMEOUT", "7")
        cfg = DaemonConfig.model_validate({"requestTimeout": 45})
        assert cfg.request_timeout == 7.0

    def test_invalid_env_keeps_config(self, monkeypatch):
        monkeypatch.setenv("AXI_REQUEST_TIMEOUT", "not-a-number")
        cfg = DaemonConfig.model_validate({"requestTimeout": 45})
        assert cfg.request_timeout == 45.0

    def test_default_without_env(self, monkeypatch):
        monkeypatch.delenv("AXI_REQUEST_TIMEOUT", raising=False)
        assert DaemonConfig.model_validate({}).request_timeout == 120.0


class TestDaemonClientErrors:
    @pytest.mark.asyncio
    async def test_connection_refused_returns_error(self, tmp_path, monkeypatch):
        """daemon 未运行时 _send 返回友好错误而非抛异常。"""
        fake_socket = str(tmp_path / "nonexistent.sock")
        monkeypatch.setattr("axi.daemon.client.SOCKET_PATH", fake_socket)

        resp = await _send(DaemonRequest(method="list_tools"))
        assert resp.status == "error"
        assert "Cannot connect to daemon" in resp.error


class TestDaemonParamsValidation:
    @pytest.mark.asyncio
    async def test_call_tool_rejects_invalid_params(self, monkeypatch):
        """daemon 在转发前按 input_schema 校验 MCP 工具入参。"""
        from axi.config import AxiConfig
        from axi.daemon.server import DaemonServer
        from axi.models import ToolMeta, ToolSource

        monkeypatch.setattr("axi.daemon.server.app_config", AxiConfig())
        server = DaemonServer()
        server.registry.register(
            ToolMeta(
                name="echo",
                server="mock",
                description="echo",
                input_schema={
                    "type": "object",
                    "properties": {"message": {"type": "string"}},
                    "required": ["message"],
                },
                source=ToolSource.MCP,
            )
        )

        resp = await server._handle_call_tool(
            DaemonRequest(method="call_tool", tool_name="mock/echo", params={})
        )
        assert resp.status == "error"
        assert "Invalid params" in resp.error

        # 数字 → string 由 _coerce_to_schema 转换，通过校验后到达连接层
        resp = await server._handle_call_tool(
            DaemonRequest(
                method="call_tool", tool_name="mock/echo", params={"message": 42}
            )
        )
        assert resp.status == "error"
        assert "not connected" in resp.error

        # 完全错误的类型（list → string）仍被拦截
        resp = await server._handle_call_tool(
            DaemonRequest(
                method="call_tool", tool_name="mock/echo", params={"message": [1]}
            )
        )
        assert resp.status == "error"
        assert "Invalid params" in resp.error

    @pytest.mark.asyncio
    async def test_call_tool_bad_schema_does_not_block(self, monkeypatch):
        """schema 含不可解析 $ref 时不拦调用（到达连接层而非校验报错）。"""
        from axi.config import AxiConfig
        from axi.daemon.server import DaemonServer
        from axi.models import ToolMeta, ToolSource

        monkeypatch.setattr("axi.daemon.server.app_config", AxiConfig())
        server = DaemonServer()
        server.registry.register(
            ToolMeta(
                name="reffy",
                server="mock",
                description="",
                input_schema={
                    "type": "object",
                    "properties": {"x": {"$ref": "#/$defs/missing"}},
                },
                source=ToolSource.MCP,
            )
        )
        resp = await server._handle_call_tool(
            DaemonRequest(method="call_tool", tool_name="mock/reffy", params={"x": 1})
        )
        assert resp.status == "error"
        assert "not connected" in resp.error


class TestCoerceToSchema:
    def test_coercions(self):
        from axi.daemon.server import _coerce_to_schema

        schema = {
            "type": "object",
            "properties": {
                "msg": {"type": "string"},
                "port": {"type": "integer"},
                "rate": {"type": "number"},
                "on": {"type": "boolean"},
            },
        }
        assert _coerce_to_schema(
            {"msg": 42, "port": "08080", "rate": "1.5", "on": "true"}, schema
        ) == {"msg": "42", "port": 8080, "rate": 1.5, "on": True}
        # 不可转换的原样保留，交给校验报错
        assert _coerce_to_schema({"port": "abc", "msg": [1]}, schema) == {
            "port": "abc",
            "msg": [1],
        }


class TestDaemonStartupWindow:
    """启动窗口：daemon 连 MCP server 期间 PID 已写、socket 未建。

    旧实现固定轮询 3 秒就报 "Failed to start daemon"，而 uvx 拉起的官方 MCP
    冷启动远超这个窗口，于是进程其实起来了、CLI 却报失败，status 也谎报 stopped。
    """

    def _use_paths(self, monkeypatch, tmp_path, pid: int | None):
        pid_path = tmp_path / "daemon.pid"
        sock_path = tmp_path / "daemon.sock"
        if pid is not None:
            pid_path.write_text(str(pid))
        monkeypatch.setattr("axi.daemon.client.PID_PATH", str(pid_path))
        monkeypatch.setattr("axi.daemon.client.SOCKET_PATH", str(sock_path))
        return sock_path

    def test_read_live_pid_none_without_file(self, tmp_path, monkeypatch):
        from axi.daemon.client import read_live_pid

        self._use_paths(monkeypatch, tmp_path, None)
        assert read_live_pid() is None

    def test_read_live_pid_none_for_dead_process(self, tmp_path, monkeypatch):
        from axi.daemon.client import read_live_pid

        # 启动失败残留的 PID 文件不能算数
        self._use_paths(monkeypatch, tmp_path, 4_000_000)
        assert read_live_pid() is None

    def test_read_live_pid_returns_current_process(self, tmp_path, monkeypatch):
        import os

        from axi.daemon.client import read_live_pid

        self._use_paths(monkeypatch, tmp_path, os.getpid())
        assert read_live_pid() == os.getpid()

    def test_is_daemon_running_requires_socket(self, tmp_path, monkeypatch):
        import os

        from axi.daemon.client import is_daemon_running

        sock = self._use_paths(monkeypatch, tmp_path, os.getpid())
        # PID 存活但 socket 未建 = 启动中
        assert is_daemon_running() is False
        sock.write_text("")
        assert is_daemon_running() is True

    def test_spawn_fails_fast_when_child_exits(self, tmp_path, monkeypatch):
        """子进程启动即退出：立刻失败，不把整个超时等满。"""
        import time

        from axi.daemon.client import _spawn_and_wait

        class ExitedProc:
            returncode = 1

            def poll(self):
                return 1

        monkeypatch.setattr("axi.daemon.client.LOG_PATH", str(tmp_path / "d.log"))
        monkeypatch.setattr("axi.daemon.client.is_daemon_running", lambda: False)
        monkeypatch.setattr(
            "axi.daemon.client.subprocess.Popen", lambda *a, **k: ExitedProc()
        )
        started = time.monotonic()
        assert _spawn_and_wait() is False
        assert time.monotonic() - started < 1.0

    def test_spawn_waits_until_timeout_when_child_alive(self, tmp_path, monkeypatch):
        """子进程活着但迟迟不就绪：等满超时才失败。"""
        import time

        from axi.daemon.client import _spawn_and_wait

        class AliveProc:
            returncode = None

            def poll(self):
                return None

        monkeypatch.setattr("axi.daemon.client.LOG_PATH", str(tmp_path / "d.log"))
        monkeypatch.setattr("axi.daemon.client.is_daemon_running", lambda: False)
        monkeypatch.setattr(
            "axi.daemon.client.subprocess.Popen", lambda *a, **k: AliveProc()
        )
        monkeypatch.setattr("axi.daemon.client._DAEMON_START_TIMEOUT", 0.3)
        started = time.monotonic()
        assert _spawn_and_wait() is False
        assert time.monotonic() - started >= 0.3

    def test_status_reports_starting(self, monkeypatch, capsys):
        import json

        from axi.cli import daemon_status

        monkeypatch.setattr("axi.cli.is_daemon_running", lambda: False)
        monkeypatch.setattr("axi.cli.read_live_pid", lambda: 4242)
        daemon_status()
        assert json.loads(capsys.readouterr().out) == {
            "status": "starting",
            "pid": 4242,
        }

    def test_status_reports_stopped(self, monkeypatch, capsys):
        import json

        from axi.cli import daemon_status

        monkeypatch.setattr("axi.cli.is_daemon_running", lambda: False)
        monkeypatch.setattr("axi.cli.read_live_pid", lambda: None)
        daemon_status()
        assert json.loads(capsys.readouterr().out) == {"status": "stopped"}

    def test_start_reports_initializing_not_failed(self, monkeypatch, capsys):
        import typer

        from axi.cli import daemon_start

        monkeypatch.setattr("axi.cli.is_daemon_running", lambda: False)
        monkeypatch.setattr("axi.cli.ensure_daemon", lambda: False)
        monkeypatch.setattr("axi.cli.read_live_pid", lambda: 4242)
        with pytest.raises(typer.Exit):
            daemon_start()
        err = capsys.readouterr().err
        assert "still initializing" in err
        assert "Failed" not in err


class TestDaemonStopWait:
    """stop 要等目标 daemon 清理完成，随后 start 才能启动新实例。"""

    def test_wait_for_exit_returns_true_when_pid_disappears(self, monkeypatch):
        from axi.daemon.client import wait_for_exit

        pids = iter([1234, 1234, None])
        monkeypatch.setattr("axi.daemon.client.read_live_pid", lambda: next(pids))
        assert wait_for_exit(1234, timeout=1.0) is True

    def test_wait_for_exit_does_not_follow_replacement(self, monkeypatch):
        from axi.daemon.client import wait_for_exit

        pids = iter([1234, 5678])
        monkeypatch.setattr("axi.daemon.client.read_live_pid", lambda: next(pids))
        assert wait_for_exit(1234, timeout=1.0) is True

    def test_wait_for_exit_times_out(self, monkeypatch):
        import time

        from axi.daemon.client import wait_for_exit

        monkeypatch.setattr("axi.daemon.client.read_live_pid", lambda: 1234)
        started = time.monotonic()
        assert wait_for_exit(1234, timeout=0.2) is False
        assert time.monotonic() - started >= 0.2

    def test_stop_waits_before_reporting(self, monkeypatch, capsys):
        from axi.cli import daemon_stop
        from axi.daemon.protocol import DaemonResponse

        waited = []
        monkeypatch.setattr("axi.cli.read_live_pid", lambda: 1234)
        monkeypatch.setattr("axi.cli.is_daemon_running", lambda: True)

        def shutdown(req):
            # 响应返回前，新 daemon 已替换 PID 文件。
            monkeypatch.setattr("axi.cli.read_live_pid", lambda: 5678)
            return DaemonResponse.success(None)

        monkeypatch.setattr("axi.cli.send_request", shutdown)
        monkeypatch.setattr(
            "axi.cli.wait_for_exit",
            lambda pid: waited.append(pid) or True,
        )

        daemon_stop()

        assert waited == [1234]
        assert "Daemon stopped." in capsys.readouterr().out

    def test_stop_starting_daemon_uses_original_pid(self, monkeypatch, capsys):
        import signal

        from axi.cli import daemon_stop

        killed = []
        waited = []
        monkeypatch.setattr("axi.cli.read_live_pid", lambda: 1234)
        monkeypatch.setattr("axi.cli.is_daemon_running", lambda: False)
        monkeypatch.setattr("axi.cli.os.kill", lambda *args: killed.append(args))
        monkeypatch.setattr(
            "axi.cli.wait_for_exit",
            lambda pid: waited.append(pid) or True,
        )
        daemon_stop()
        assert killed == [(1234, signal.SIGTERM)]
        assert waited == [1234]
        assert "Daemon stopped." in capsys.readouterr().out

    def test_stop_reports_failure_when_process_outlives_timeout(
        self, monkeypatch, capsys
    ):
        import typer

        from axi.cli import daemon_stop
        from axi.daemon.protocol import DaemonResponse

        monkeypatch.setattr("axi.cli.read_live_pid", lambda: 1234)
        monkeypatch.setattr("axi.cli.is_daemon_running", lambda: True)
        monkeypatch.setattr(
            "axi.cli.send_request", lambda req: DaemonResponse.success(None)
        )
        monkeypatch.setattr("axi.cli.wait_for_exit", lambda pid: False)

        with pytest.raises(typer.Exit):
            daemon_stop()
        assert "did not exit" in capsys.readouterr().err
