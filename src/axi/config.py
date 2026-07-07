"""axi 配置中心：Pydantic 模型化，统一加载 axi.json，全局共享。"""

import hashlib
import json
import logging
import os
import sys
from pathlib import Path

from pydantic import BaseModel, Field, model_validator

logger = logging.getLogger(__name__)

AXI_HOME = Path("~/.axi").expanduser()
CONFIG_PATH = (
    Path(os.environ.get("AXI_CONFIG", AXI_HOME / "axi.json")).expanduser().resolve()
)
# 每份配置的隔离键：daemon socket/pid/log 与 embedding 缓存都按它分目录，
# 多项目（多份 AXI_CONFIG）互不干扰。
CONFIG_HASH = hashlib.sha256(str(CONFIG_PATH).encode()).hexdigest()[:12]


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
    request_timeout: float = Field(
        default=120,
        alias="requestTimeout",
        description="CLI 等待 daemon 单个请求的超时（秒），含工具调用",
    )

    @model_validator(mode="before")
    @classmethod
    def override_with_env(cls, values: dict) -> dict:
        # 环境变量 AXI_REQUEST_TIMEOUT 优先于 axi.json（长工具调用可临时调高）
        if isinstance(values, dict):
            env = os.environ.get("AXI_REQUEST_TIMEOUT")
            if env:
                try:
                    values["requestTimeout"] = float(env)
                except ValueError:
                    logger.warning("Ignoring invalid AXI_REQUEST_TIMEOUT=%r", env)
        return values


class MCPServerConfig(BaseModel):
    """单个 MCP server 的配置。"""

    command: str | None = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] | None = None
    url: str | None = None
    headers: dict[str, str] | None = None


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


def _warn_ignored_local_config() -> None:
    """0.0.6 起不再读 cwd 的 axi.json；发现被忽略的本地配置时给出迁移提示。"""
    if "AXI_CONFIG" not in os.environ and Path("axi.json").is_file():
        print(
            "Warning: ./axi.json found but ignored (axi now reads "
            f"{CONFIG_PATH}). Set AXI_CONFIG=./axi.json to use it.",
            file=sys.stderr,
        )


def _load_app_config() -> AxiConfig:
    """延迟加载配置，捕获异常并输出友好信息。"""
    _warn_ignored_local_config()
    try:
        return load_config(CONFIG_PATH)
    except SystemExit:
        raise
    except Exception as e:
        raise SystemExit(f"Error: Failed to load config: {e}")


app_config: AxiConfig = _load_app_config()
