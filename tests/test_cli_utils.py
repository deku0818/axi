"""CLI 辅助函数测试：_parse_params、_extract_option、_output_json。"""

import json

import pytest
from pydantic import ValidationError

from axi.cli import _parse_params, _extract_option
from axi.config import AxiConfig, load_config
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
