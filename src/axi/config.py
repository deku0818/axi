"""axi 配置中心：Pydantic 模型化，统一加载 axi.json，全局共享。"""

import json
import logging
import os
from pathlib import Path

from pydantic import BaseModel, Field, model_validator

logger = logging.getLogger(__name__)

CONFIG_PATH = Path("axi.json")


# ── 子配置模型 ──────────────────────────────────────────────


class CliConfig(BaseModel):
    """CLI 显示配置。"""

    rich: bool = Field(default=False, description="启用 Rich 格式化输出")

    @model_validator(mode="before")
    @classmethod
    def override_with_env(cls, values: dict) -> dict:
        if isinstance(values, dict):
            env = os.environ.get("AXI_RICH", "").lower()
            if env in ("1", "true"):
                values["rich"] = True
            elif env in ("0", "false"):
                values["rich"] = False
        return values


class EmbeddingConfig(BaseModel):
    """Embedding 搜索配置。"""

    provider: str | None = Field(default=None, description="jina 或 openai")
    api_key: str | None = Field(default=None, alias="apiKey", description="API 密钥")
    model: str | None = Field(default=None, description="模型名称")
    base_url: str | None = Field(
        default=None, alias="baseUrl", description="自定义端点"
    )

    @model_validator(mode="before")
    @classmethod
    def override_with_env(cls, values: dict) -> dict:
        if isinstance(values, dict) and not values.get("apiKey"):
            provider = values.get("provider", "")
            if provider == "jina":
                values["apiKey"] = os.environ.get("JINA_API_KEY")
            elif provider == "openai":
                values["apiKey"] = os.environ.get("OPENAI_API_KEY")
        return values


class SearchWeightsConfig(BaseModel):
    """混合搜索 RRF 融合权重。"""

    bm25: float = Field(default=0.3, description="BM25 权重")
    embedding: float = Field(default=0.7, description="Embedding 权重")


class SearchConfig(BaseModel):
    """搜索引擎配置。"""

    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    weights: SearchWeightsConfig = Field(default_factory=SearchWeightsConfig)


class DaemonConfig(BaseModel):
    """Daemon 进程配置。"""

    idle_timeout_minutes: int = Field(
        default=30, alias="idleTimeoutMinutes", description="空闲自动关闭（分钟）"
    )


class MCPServerConfig(BaseModel):
    """单个 MCP server 的配置。"""

    command: str | None = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] | None = None
    url: str | None = None


class NativeToolEntry(BaseModel):
    """原生工具模块声明。"""

    module: str = Field(description="Python 模块路径或文件路径")
    name: str | None = Field(default=None, description="server 名，省略时自动推导")


# ── 主配置 ──────────────────────────────────────────────


class AxiConfig(BaseModel):
    """axi 主配置。"""

    cli: CliConfig = Field(default_factory=CliConfig)
    mcp_servers: dict[str, MCPServerConfig] = Field(
        default_factory=dict, alias="mcpServers"
    )
    native_tools: list[NativeToolEntry] = Field(
        default_factory=list, alias="nativeTools"
    )
    search: SearchConfig = Field(default_factory=SearchConfig)
    daemon: DaemonConfig = Field(default_factory=DaemonConfig)


# ── 加载 ──────────────────────────────────────────────


def load_config(path: Path) -> AxiConfig:
    """读取并解析配置文件。找不到文件则返回默认配置，格式错误则报错退出。"""
    if not path.exists():
        return AxiConfig()
    with open(path) as f:
        try:
            raw = json.load(f)
        except json.JSONDecodeError as e:
            raise SystemExit(f"Error: Malformed config file {path}: {e}")
    try:
        return AxiConfig.model_validate(raw)
    except Exception as e:
        raise SystemExit(f"Error: Invalid config in {path}: {e}")


def _load_app_config() -> AxiConfig:
    """延迟加载配置，捕获异常并输出友好信息。"""
    try:
        return load_config(CONFIG_PATH)
    except SystemExit:
        raise
    except Exception as e:
        raise SystemExit(f"Error: Failed to load config: {e}")


app_config: AxiConfig = _load_app_config()
