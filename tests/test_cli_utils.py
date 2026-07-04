"""CLI 辅助函数测试：_parse_params、_extract_option、_output_json。"""

import json
from unittest.mock import patch

import pytest
from pydantic import ValidationError

import axi.cli as cli
from axi.cli import _parse_params, _extract_option, _search_and_merge
from axi.config import AxiConfig, load_config
from axi.daemon.protocol import DaemonResponse
from axi.models import SearchResult, ToolSource
from axi.providers.mcp import MCPServerConfig


# ── _parse_params ──────────────────────────────────────────


class TestParseParams:
    def test_key_value_pair(self):
        result = _parse_params(["--name", "alice"])
        assert result == {"name": "alice"}

    def test_boolean_flag(self):
        result = _parse_params(["--verbose"])
        assert result == {"verbose": True}

    def test_json_value_auto_parsed(self):
        result = _parse_params(["--data", '{"x": 1}'])
        assert result == {"data": {"x": 1}}

    def test_numeric_value_auto_parsed(self):
        result = _parse_params(["--count", "42"])
        assert result == {"count": 42}

    def test_multiple_params(self):
        result = _parse_params(["--name", "alice", "--age", "30", "--verbose"])
        assert result == {"name": "alice", "age": 30, "verbose": True}

    def test_boolean_flag_before_another_flag(self):
        result = _parse_params(["--verbose", "--name", "alice"])
        assert result == {"verbose": True, "name": "alice"}

    def test_empty_args(self):
        result = _parse_params([])
        assert result == {}

    def test_no_schema_keeps_json_guessing(self):
        # 无 schema（未知字段 / **kwargs 工具）退回旧行为：按 JSON 猜类型
        assert _parse_params(["--flag", "true"]) == {"flag": True}
        assert _parse_params(["--n", "42"]) == {"n": 42}


class TestParseParamsSchemaAware:
    """F：string 字段的值不应被 json.loads 误转成布尔/数字/null。"""

    SCHEMA = {
        "properties": {
            "text": {"type": "string"},
            "count": {"type": "integer"},
            "active": {"type": "boolean"},
            "opt": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        }
    }

    def test_string_field_keeps_literal(self):
        assert _parse_params(["--text", "true"], self.SCHEMA) == {"text": "true"}
        assert _parse_params(["--text", "null"], self.SCHEMA) == {"text": "null"}
        assert _parse_params(["--text", "42"], self.SCHEMA) == {"text": "42"}

    def test_optional_string_keeps_literal(self):
        assert _parse_params(["--opt", "false"], self.SCHEMA) == {"opt": "false"}

    def test_non_string_fields_still_parsed(self):
        assert _parse_params(["--count", "42"], self.SCHEMA) == {"count": 42}
        assert _parse_params(["--active", "true"], self.SCHEMA) == {"active": True}

    def test_unknown_key_falls_back_to_json(self):
        assert _parse_params(["--misc", "true"], self.SCHEMA) == {"misc": True}


# ── _extract_option ──────────────────────────────────────


class TestExtractOption:
    def test_extract_long_option(self):
        value, remaining = _extract_option(
            ["--json", '{"a":1}', "--verbose"], "--json", "-j"
        )
        assert value == '{"a":1}'
        assert remaining == ["--verbose"]

    def test_extract_short_option(self):
        value, remaining = _extract_option(["-j", '{"a":1}'], "--json", "-j")
        assert value == '{"a":1}'
        assert remaining == []

    def test_option_not_present(self):
        value, remaining = _extract_option(["--verbose", "--name", "x"], "--json", "-j")
        assert value is None
        assert remaining == ["--verbose", "--name", "x"]


# ── _search_and_merge ──────────────────────────────────────


class TestSearchAndMerge:
    def _run(self, local, mcp_data, top_k):
        """跑一次合并，返回输出的 JSON 列表。"""
        resp = DaemonResponse.success(mcp_data)
        captured = {}
        with (
            patch.object(cli, "daemon_request", return_value=resp),
            patch.object(cli.typer, "echo", lambda s: captured.setdefault("out", s)),
        ):
            _search_and_merge(local, "search", "q", top_k)
        return json.loads(captured["out"])

    def test_local_and_mcp_concatenated(self):
        # 本地在前、MCP 在后，各自顺序保留
        local = [
            SearchResult(name="n/a", description="", source=ToolSource.NATIVE),
            SearchResult(name="n/b", description="", source=ToolSource.NATIVE),
        ]
        mcp = [{"name": "m/x", "description": "", "source": "mcp"}]
        out = self._run(local, mcp, top_k=5)
        assert [r["name"] for r in out] == ["n/a", "n/b", "m/x"]

    def test_no_score_field_in_output(self):
        local = [SearchResult(name="n/a", description="", source=ToolSource.NATIVE)]
        mcp = [{"name": "m/x", "description": "", "source": "mcp"}]
        out = self._run(local, mcp, top_k=5)
        assert all("score" not in r for r in out)

    def test_daemon_failure_still_returns_local(self):
        local = [SearchResult(name="n/a", description="", source=ToolSource.NATIVE)]
        captured = {}
        with (
            patch.object(
                cli, "daemon_request", return_value=DaemonResponse.fail("boom")
            ),
            patch.object(cli.typer, "echo", lambda s: captured.setdefault("out", s)),
        ):
            _search_and_merge(local, "search", "q", 5)
        assert [r["name"] for r in json.loads(captured["out"])] == ["n/a"]


# ── doctor ─────────────────────────────────────────────────


class TestDoctor:
    def _run(self, monkeypatch, config_dict):
        cfg = AxiConfig.model_validate(config_dict)
        monkeypatch.setattr(cli, "app_config", cfg)
        captured = {}
        monkeypatch.setattr(cli.typer, "echo", lambda s: captured.setdefault("out", s))
        exit_code = 0
        try:
            cli.doctor()
        except cli.typer.Exit as e:
            exit_code = e.exit_code
        return json.loads(captured["out"]), exit_code

    def test_clean_config_ok(self, monkeypatch):
        report, code = self._run(monkeypatch, {})
        assert report["ok"] is True
        assert code == 0
        assert report["embedding"]["provider"] is None

    def test_missing_embedding_key_flagged(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        report, code = self._run(
            monkeypatch, {"search": {"embedding": {"provider": "openai"}}}
        )
        assert report["ok"] is False
        assert code == 1
        assert report["embedding"]["api_key"] == "missing"
        assert any("API key" in i for i in report["issues"])


# ── MCPServerConfig validator ──────────────────────────────


class TestMCPServerConfig:
    def test_missing_command_and_url_rejected(self):
        with pytest.raises(
            ValidationError, match="must have either 'command' or 'url'"
        ):
            MCPServerConfig(server="test")

    def test_command_only_ok(self):
        cfg = MCPServerConfig(server="test", command="python")
        assert cfg.command == "python"

    def test_url_only_ok(self):
        cfg = MCPServerConfig(server="test", url="http://localhost:8080")
        assert cfg.url == "http://localhost:8080"

    def test_empty_server_rejected(self):
        with pytest.raises(ValidationError):
            MCPServerConfig(server="", command="python")


# ── load_config ──────────────────────────────────────


class TestLoadAxiConfig:
    def test_missing_file_returns_default(self, tmp_path):
        result = load_config(tmp_path / "nonexistent.json")
        assert result == AxiConfig()

    def test_malformed_json_raises_system_exit(self, tmp_path):
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("{invalid json")
        with pytest.raises(SystemExit, match="Malformed config file"):
            load_config(bad_file)

    def test_valid_json(self, tmp_path):
        good_file = tmp_path / "axi.json"
        good_file.write_text(json.dumps({"mcpServers": {}}))
        result = load_config(good_file)
        assert result.mcp_servers == {}
