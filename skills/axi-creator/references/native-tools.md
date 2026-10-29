# 原生工具：schema、变量与包分发

## 输入 schema 与验证

axi 根据函数签名和类型注解创建 Pydantic 参数模型，再导出 JSON Schema。使用实际类型表达业务约束，避免让 Agent 仅靠自然语言猜值：

```python
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from axi import tool


class TimeRange(BaseModel):
    start: str
    end: str


@tool(
    name="query_device_data",
    description="查询设备在指定时间范围内的遥测数据，支持 cn、jp、us 区域",
    output_example={"device_id": "device01", "rows": []},
)
def query_device_data(
    device_id: Annotated[str, Field(description="设备唯一 ID", min_length=8)],
    region: Literal["cn", "jp", "us"],
    time_range: TimeRange,
    fields: list[str] | None = None,
    limit: Annotated[int, Field(ge=1, le=1000)] = 100,
) -> dict:
    # 在这里连接实际 API / SDK；此示例只演示输入类型与返回形状
    return {"device_id": device_id, "rows": []}
```

- `Literal` 导出枚举，`Annotated[..., Field(...)]` 导出字段说明与约束。
- 嵌套 `BaseModel` 通过 JSON Schema 的定义和引用表达，调用时将输入 dict 转成对应模型实例。
- `str | None` 允许 null；只有提供默认值才使参数可省略。
- 未声明字段默认不允许；函数含 `**kwargs` 时允许额外字段，但额外字段不会自动获得明确的 schema。`*args` 不进入参数 schema。面向 Agent 的主要输入应显式声明，支持关键字传参。
- 工具描述用于发现，参数描述用于 describe；当前 BM25 / embedding 语料只有工具完整名和工具级 description。
- `output_example` 可经 describe 查看，也会追加到 MCP 平铺工具描述中；它不生成或验证输出 schema。返回值应符合对下游承诺的结构。
- 同步和 `async def` 原生函数都可被执行，公开 PTC 句柄仍是同步函数。已有 async 调用方使用 `await asyncio.to_thread(handle, **params)`，避免在事件循环线程内直接调用。

## 环境与请求级变量

使用 `axi.env` 兼容 CLI / stdio 环境变量以及 HTTP MCP 请求级变量：

```python
from axi import env, tool


@tool(name="service_region", description="读取当前服务区域配置")
def service_region() -> dict:
    return {"region": env("REGION", "cn")}
```

需要密钥时，在工具函数内部读取 `env("API_KEY")`，缺失时报可操作的错误，不返回密钥。读取优先级是当前请求的 `Axi-*` header，然后是服务进程环境变量；普通 CLI / stdio 只读进程环境。不要在 import 阶段缓存请求级值。

`Axi-API-KEY` 映射为 `API_KEY`，`Axi-REGION` 映射为 `REGION`。请求级变量机制作用于原生工具读取，不会自动改写 daemon 已有 MCP 连接的环境或认证头；上游 MCP 凭据通过 `mcpServers[].env / headers` 配置。

## 选择注册方式

### 项目内：nativeTools

```json
{
  "nativeTools": [
    {"module": "./tools.py", "name": "orders"},
    {"module": "my_pkg.analytics"}
  ]
}
```

`.py` 路径相对配置目录；模块路径使用 Python import 机制，需要相应包及其依赖安装在执行 axi 的环境中。省略组名时以上第二项归入 `analytics`。

### 包分发：entry points

扩展包在 `pyproject.toml` 中声明：

```toml
[project.entry-points."axi.native_tools"]
orders = "orders_axi.tools"
```

`orders_axi.tools` 包含 `@tool` 函数；value 使用可 import 的模块路径。将扩展包安装到运行 axi CLI / PTC 的同一个 Python 环境，随后自动发现，不需要重复添加 `nativeTools`。例如项目环境可执行 `uv add axi-cli <extension-package>`，再用 `uv run axi ...`；CLI 若安装在 uv tool 的隔离环境，则可用 `uv tool install --with <extension-package> axi-cli` 安装扩展。

自动发现按模块路径去重，先处理显式 `nativeTools`，再处理 entry points，因此同模块的显式配置组名优先。不同模块使用同一组名会警告并合并，选择独立、稳定的组名与工具名，避免重名覆盖。

## 验证与分发

检查 schema、真实调用数据及 Python PTC 是否一致；有输入约束时验证一个典型无效参数是否得到清晰错误。对 HTTP API 包装可模拟上游，避免测试写操作产生额外业务变更。

如果分发范围包含 Agent skill，保留 skill 目录里的 `references/`，不要让技能依赖未随包分发的仓库文档。
