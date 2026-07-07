---
name: axi-creator
description: Expose an existing capability (Python function, HTTP API, third-party SDK, or MCP server) as an axi tool, or export registered axi tools as an MCP server. Use when the user wants to "add a tool to axi", "wrap an API for axi", "register a function", "make X callable via `axi run`", "expose these tools over MCP / hook them to Claude Desktop" (`axi mcp`), or needs to build a new `@tool` / configure `mcpServers` / publish a native-tool package. Covers decorator usage, schema quality via type hints, registration via `axi.json` vs `pyproject.toml` entry_points, MCP export, and end-to-end self-verification. Use `axi-use` instead when the task is to call existing tools rather than register new ones.
---

# axi — 工具接入手册

把一个能力变成 axi 工具，**先选路径，再写注册，最后自测**。

## 选路径（按起点决定）

| 起点 | 走哪条 | 工作量 |
|---|---|---|
| 已有 MCP server（能跑命令或暴露 HTTP 端点） | **Path B：改 `axi.json` 的 `mcpServers`** | 1 行 JSON |
| 有 Python 函数 / 想包装 HTTP API 或第三方 SDK | **Path A：写 `@tool` 装饰器** | 函数 + 几行注册 |
| 要把工具以 pip 包分发给别人 | Path A + entry_points | 加 1 段 pyproject.toml |

---

## Path A：`@tool` 装饰器

最小示例（放进任意 Python 文件，比如 `my_tools.py`）：

```python
from axi import tool

@tool(
    name="query_orders",                      # 可选，缺省用函数名
    description="按区域查询订单",              # 可选，缺省用 docstring
    output_example={"orders": [...], "total": 1},  # 可选，但强烈建议写
)
def query_orders(region: str, limit: int = 10) -> dict:
    return {"orders": [...], "total": 1}
```

**就这一步就够了——函数被 import 时自动注册。** `input_schema` 由 axi 从 type hints 提取（用 Pydantic `create_model`），不用自己写 JSON Schema。

### 写出好 schema（决定 Agent 用起来的难度）

axi 支持 Pydantic 能支持的一切。**越严格，Agent 传错参数的概率越低**：

```python
from typing import Annotated, Literal
from pydantic import BaseModel, Field

class TimeRange(BaseModel):
    start: str
    end: str

@tool(description="查询设备的 CAN 数据")
def get_can_data(
    device_id: Annotated[str, Field(description="设备唯一 ID", min_length=8)],
    region: Literal["cn", "jp", "us"],              # 枚举 → agent 不会猜错
    range: TimeRange,                               # 嵌套 object schema
    fields: list[str] | None = None,                # 可选 list
    limit: Annotated[int, Field(ge=1, le=1000)] = 100,
) -> dict: ...
```

要点：
- **必传参数不给默认值**；可选参数一律给默认值（Agent 会省略）
- 用 `Literal[...]` 表达枚举，比 `str` + 文档说明更可靠
- 用 `Annotated[T, Field(description=...)]` 在 schema 里塞字段说明；**`description` 文本会被 BM25/Embedding 搜到**——写清楚利己利人
- 复杂输入用 `BaseModel` 嵌套；axi 会把它展开成 object schema
- **填 `output_example`**：MCP 协议没有 output schema，原生工具是 axi 独有的优势——Agent 能在 `axi describe` 里直接看到返回形状，不用试跑一遍

### 凭据与配置变量：用 `axi.env`，别用 `os.environ`

工具里需要 API Key 等变量时，一律通过 `axi.env(name, default=None)` 读取：

```python
import axi

@tool(description="调用上游 API")
def call_api(query: str) -> dict:
    key = axi.env("API_KEY")   # CLI/stdio 下读环境变量；HTTP 导出时读客户端 Axi-* header
    ...
```

CLI 和 stdio 形态下它就是环境变量；但当工具经 `axi mcp --transport http` 导出为共享 HTTP server 时，每个客户端可通过 `Axi-*` 请求头传自己的变量（见下文"导出为 MCP server"），`axi.env` 会优先取当前请求的值。直接 `os.environ` 的工具在 HTTP 形态下拿不到客户端变量。

### 注册：两种方式，二选一

**方式 1：本项目内用 → `axi.json` 的 `nativeTools`**

```json
{
  "nativeTools": [
    { "module": "./tools/my_tools.py" },          // 文件路径，server 名自动推导为 my_tools
    { "module": "my_pkg.tools", "name": "my" }    // 模块路径，显式指定 server
  ]
}
```

`axi.json` 是 `AXI_CONFIG` 环境变量指向的文件（缺省 `~/.axi/axi.json`，**不会从当前目录发现**）。项目级配置在项目里放一份 axi.json 并 `export AXI_CONFIG=/path/to/axi.json`（direnv 最省事）。

**方式 2：分发给别人用 → pip 包 + `pyproject.toml` entry_points**

```toml
[project.entry-points."axi.native_tools"]
smartlink = "smartlink_axi.tools"
```

装完 `pip install <你的包>` 后，**无需 axi.json** 也能 `axi list` 看到；group 名必须是 `axi.native_tools`，value 必须是模块路径（不要写 `.py` 文件）。

合并规则：同模块两边都声明时 `axi.json` 赢；不同模块声明同一个 server 名会 log warning 但照常挂载（工具合并）。

---

## Path B：接入已有 MCP server

编辑 `AXI_CONFIG` 指向的 `axi.json`（缺省 `~/.axi/axi.json`）：

```json
{
  "mcpServers": {
    "myserver": {                                   // key 就是 server 名
      "command": "npx", "args": ["some-mcp-tool"],  // 本地进程
      "env": {"API_KEY": "xxx"}
    },
    "remote": {
      "url": "http://localhost:8000/mcp",           // 或 HTTP streaming
      "headers": {"Authorization": "Bearer xxx"}    // 可选：远端要求认证时随每个请求附带
    }
  }
}
```

`command` / `url` 二选一；凭据传递按 transport 选字段——stdio 用 `env`（注入子进程环境），HTTP 用 `headers`（附到每个请求）。保存后直接 `axi list` 就能看到新工具——daemon 会按需自动拉起连接。

---

## 自测（三步，必做）

注册完后走一遍 Agent 视角的发现→调用路径，验证 schema 生成正确：

```bash
axi list                                    # 新 server / 工具出现了？
axi search "你的工具描述里的关键词"           # 能被语义搜到？搜不到 → description 要改
axi describe <server>/<tool>                # input_schema 字段、类型、required 对不对？
axi run <server>/<tool> --key value          # 跑通，返回 {"status":"success","data":...}
```

**搜不到比跑不通更常见**——description 太短、只写了类名或方法名都会导致 BM25/Embedding 召回差。用几个真实查询跑 `axi search`，看你的工具有没有出现、排得够不够靠前。

---

## 导出为 MCP server（写一次，CLI + MCP 两用）

注册进 axi 的工具（native 和 MCP 都行）可以一条命令变成 MCP server，挂给 Claude Desktop / Claude Code 等任何 MCP 客户端：

```bash
axi mcp --server my_tools    # 平铺：每个工具是独立 MCP tool（单 server 用裸名，多 server 加 server__ 前缀）
axi mcp                      # 元工具：只暴露 search/grep/describe/run 四个工具，工具再多也不吃对端 context
axi mcp --server a,b --transport http --port 8321    # HTTP 长驻服务
```

缺省形态自动判定：指定了 `--server` → 平铺，全量 → 元工具；`--flat` / `--meta` 强制覆盖。

客户端配置示例——stdio 进程由客户端拉起、cwd 不可控，**必须在 env 里用 `AXI_CONFIG` 锚定配置**：

```json
{
  "mcpServers": {
    "my-tools": {
      "command": "axi",
      "args": ["mcp", "--server", "my_tools"],
      "env": { "AXI_CONFIG": "/path/to/axi.json" }
    }
  }
}
```

### HTTP 形态下给每个客户端传变量：`Axi-*` header

stdio 是一客户端一进程，变量走 `env` 即可；HTTP 是共享进程，进程环境变量在启动时定死，**每个客户端的变量改走请求头**。约定：`Axi-<名字>` 映射为变量名（去前缀、`-`→`_`、转大写），工具内用 `axi.env` 读取，请求级值优先于进程环境变量：

```json
{
  "mcpServers": {
    "my-tools": {
      "url": "http://your-host:8321/mcp",
      "headers": { "Axi-API-KEY": "sk_xxx", "Axi-REGION": "cn" }
    }
  }
}
```

工具里 `axi.env("API_KEY")` 即得 `sk_xxx`，不同客户端互不可见。注意：这解决的是"客户端带变量进来"，不是服务端准入控制——公网暴露时另需网关层鉴权。

---

## 反模式

- 函数签名用 `**kwargs` 或 `*args` — schema 提取不到参数，Agent 看到空 schema 会乱传
- 所有参数都写 `str` — 失去类型约束和枚举提示，Agent 要靠 describe 里的自然语言猜
- `description` 只写一个词（"搜索"、"查询"）— BM25 召回差、Embedding 语义稀薄
- 返回不稳定结构（同一工具有时返 list 有时返 dict）— 下游 Agent 没法写聚合逻辑
- 把敏感配置（API Key）硬编码在 `@tool` 函数里 — 用 `axi.env` 读取（MCP server 的凭据走 `mcpServers[...].env` / `headers`）
- entry_points 的 value 写成文件路径 `"pkg/tools.py"` — 必须是可 import 的模块路径 `"pkg.tools"`

---

需要更多配置细节（`search` embedding、`daemon` idle 超时、`AXI_CONFIG` 环境变量改 axi.json 路径等）时，直接读源码：axi 包里的 `config.py` 是 Pydantic 模型，字段和默认值一目了然；`axi --help` 查命令参数。
