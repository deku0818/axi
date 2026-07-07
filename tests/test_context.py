"""axi.env 请求级变量：header 映射与读取优先级。"""

import pytest

import axi
from axi.context import set_request_env


@pytest.fixture(autouse=True)
def _clean_request_env():
    set_request_env(None)
    yield


def test_env_falls_back_to_os_environ(monkeypatch):
    monkeypatch.setenv("AXI_TEST_VAR", "from-env")
    assert axi.env("AXI_TEST_VAR") == "from-env"


def test_request_env_overrides_os_environ(monkeypatch):
    monkeypatch.setenv("AXI_TEST_VAR", "from-env")
    set_request_env({"axi-axi-test-var": "from-header"})
    assert axi.env("AXI_TEST_VAR") == "from-header"


def test_env_missing_returns_default():
    assert axi.env("AXI_NO_SUCH_VAR") is None
    assert axi.env("AXI_NO_SUCH_VAR", "fallback") == "fallback"


def test_header_name_mapping():
    set_request_env(
        {
            "axi-a": "1",
            "axi-github-token": "ghp_x",
            "authorization": "Bearer t",
            "content-type": "application/json",
        }
    )
    assert axi.env("A") == "1"
    assert axi.env("GITHUB_TOKEN") == "ghp_x"
    assert axi.env("AUTHORIZATION") is None
    assert axi.env("CONTENT_TYPE") is None
