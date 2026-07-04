"""axi 核心数据模型。"""

from enum import Enum
from typing import Any, Literal, Self

from pydantic import BaseModel, Field, model_validator


def allowed_types(prop: dict) -> set[str]:
    """提取属性 schema 允许的原始类型，覆盖 type 为字符串/列表及 anyOf 分支（递归）。"""
    types: set[str] = set()
    t = prop.get("type")
    if isinstance(t, str):
        types.add(t)
    elif isinstance(t, list):
        types.update(x for x in t if isinstance(x, str))
    for branch in prop.get("anyOf", []):
        if isinstance(branch, dict):
            types |= allowed_types(branch)
    return types


class ToolSource(str, Enum):
    """工具来源类型。"""

    NATIVE = "native"
    MCP = "mcp"


class ToolMeta(BaseModel):
    """工具元数据，Registry 中的核心单元。"""

    name: str = Field(min_length=1, description="工具名称")
    server: str | None = Field(
        default=None, description="所属 server 名称（MCP server 或原生工具模块名）"
    )
    description: str = Field(description="工具描述")
    input_schema: dict[str, Any] = Field(
        default_factory=dict, description="输入参数 JSON Schema"
    )
    output_example: Any | None = Field(
        default=None, description="输出示例（原生工具可选提供）"
    )
    source: ToolSource = Field(description="工具来源")

    @model_validator(mode="after")
    def _validate_fields(self) -> Self:
        if "/" in self.name:
            raise ValueError(f"Tool name must not contain '/': {self.name!r}")
        if self.source == ToolSource.MCP and not self.server:
            raise ValueError("MCP tool must have a server name")
        return self

    @property
    def full_name(self) -> str:
        """完整工具名，含 server 前缀。"""
        if self.server:
            return f"{self.server}/{self.name}"
        return self.name


class ResultEnvelope(BaseModel):
    """统一结果信封基类。"""

    status: Literal["success", "error"] = Field(description="success 或 error")
    data: Any | None = Field(default=None, description="执行结果")
    error: str | None = Field(default=None, description="错误信息")

    @classmethod
    def success(cls, data: Any) -> Self:
        return cls(status="success", data=data)

    @classmethod
    def fail(cls, error: str) -> Self:
        return cls(status="error", error=error)


class RunResult(ResultEnvelope):
    """axi run 的统一输出信封。"""


class SearchResult(BaseModel):
    """搜索结果条目。

    不含相关性分数：native（本地）与 MCP（daemon）来自两套独立索引、
    各自归一化，跨源分数不可比，暴露出来只会误导 Agent。结果按相关性
    排序即可，顺序本身就是信号。
    """

    name: str = Field(description="工具完整名称")
    description: str = Field(description="工具描述")
    source: ToolSource = Field(description="工具来源")
