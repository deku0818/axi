"""Daemon 客户端测试：连接错误处理和超时。"""

import pytest

from axi.daemon.client import _send
from axi.daemon.protocol import DaemonRequest


class TestDaemonClientErrors:
    @pytest.mark.asyncio
    async def test_connection_refused_returns_error(self, tmp_path, monkeypatch):
        """daemon 未运行时 _send 返回友好错误而非抛异常。"""
        fake_socket = str(tmp_path / "nonexistent.sock")
        monkeypatch.setattr("axi.daemon.client.SOCKET_PATH", fake_socket)

        resp = await _send(DaemonRequest(method="list_tools"))
        assert resp.status == "error"
        assert "Cannot connect to daemon" in resp.error
