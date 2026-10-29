# axi

**Agent eXecution Interface — 让 Agent 按需发现外部工具，用 CLI、MCP 或 Python 代码统一调用。**

axi 将已有 MCP server 和 Python 函数接入同一套工具接口。API、第三方 SDK 和业务逻辑可以包装成 Python 函数，一次注册，同时获得 CLI、MCP 和程序化调用能力；已有 MCP 工具也可以直接转为 CLI 和 Python 调用。

## 为什么需要 axi？

### 按需发现，减少上下文中的工具定义

当 MCP 客户端把所有工具定义预先提供给模型时，即使一次任务只用 30 个工具中的一两个，其余工具的描述和参数 schema 仍会占据上下文。低频工具也会带来持续的 token 开销。

axi 采用**渐进式披露（Progressive Disclosure）**：工具保存在 axi 的注册表中，Agent 需要某项能力时再搜索，只读取候选工具的完整参数。

```text
search / grep → 工具摘要 → describe → 参数 schema → run
```

通过 CLI 使用时，无需把这些工具逐个注册到模型的工具列表；偏好 MCP 的 Agent 可以只接入 `search / grep / describe / run` 四个元工具。发现结果、选中工具的 schema 和执行结果仍会进入上下文，但无需预先加载整个工具集。

### 用代码组合调用，减少模型往返

**PTC（Programmatic Tool Calling）**允许 Agent 写一段 Python，完成循环、批量调用、工具之间的数据传递，以及本地过滤和聚合，再把需要的结果返回给模型。

这样无需让模型为每一步分别生成调用参数、等待结果、再决定下一次调用。独立请求还可以在代码中安排并发；axi 的 Python 调用接口本身是同步的，并发由调用方控制。

### 一次接入，多种使用方式

```text
已有 MCP server ─────────┐                 ┌─ CLI：axi search / describe / run
                       ├─ axi 工具注册表 ─┼─ Python：tool("server/name")(**params)
API / SDK / 函数 → @tool ┘                 └─ MCP：四个元工具 / 逐个暴露工具
```

| 需求 | 使用方式 |
|---|---|
| Agent 能执行 shell 命令 | 用 CLI 搜索、查看和调用工具 |
| 批量执行、跨工具组合、过滤聚合 | 用 Python PTC，将流程写成程序 |
| Agent 使用 MCP，需要按需发现大量工具 | 用 `axi mcp` 导出四个元工具 |
| MCP 客户端需要直接看到某组工具 | 用 `axi mcp --server <name>` 平铺导出 |

## 安装

需要 Python 3.12+。当前 daemon 使用 Unix socket 和 `fcntl`，适用于 macOS / Linux；Windows 可在 WSL 中使用。

```bash
# 安装 CLI（包名是 axi-cli，命令名是 axi）
uv tool install axi-cli

# 在 Python 项目中使用 PTC，将 axi 安装到该项目环境
uv add axi-cli

# 从源码开发
uv sync
uv run axi --help
```

`uv tool install` 使用隔离环境，不会让其他 Python 环境自动获得 `import axi`。临时运行 PTC 脚本也可以使用 `uv run --with axi-cli python batch.py`。

## 五分钟跑通：一个函数，三个入口

下面的示例只使用本地数据，无需 API key 或外部服务。

### 1. 定义工具

在项目目录创建 `tools.py`：

```python
from axi import tool


@tool(
    name="query_orders",
    description="按区域查询订单，返回订单金额和匹配总数；支持 cn、jp、us 区域",
    output_example={
        "orders": [{"id": 1, "region": "cn", "amount": 120}],
        "total": 1,
    },
)
def query_orders(region: str, limit: int = 10) -> dict:
    orders = [
        {"id": 1, "region": "cn", "amount": 120},
        {"id": 2, "region": "jp", "amount": 80},
        {"id": 3, "region": "us", "amount": 60},
    ]
    matched = [order for order in orders if order["region"] == region]
    return {"orders": matched[:limit], "total": len(matched)}
```

将 API 请求或 SDK 调用放进函数体，就可以用相同方式接入外部系统。axi 从函数签名和类型注解生成输入 schema；`description` 默认取 docstring，`output_example` 可选，用于帮助 Agent 编写结果处理代码。

### 2. 注册并通过 CLI 调用

在同一目录创建 `axi.json`：

```json
{
  "nativeTools": [
    {"module": "./tools.py", "name": "orders"}
  ]
}
```

```bash
export AXI_CONFIG="$PWD/axi.json"

axi search "按区域查询订单" -k 3
axi describe orders/query_orders
axi run orders/query_orders --region cn --limit 5
```

最后一条命令返回：

```json
{"status":"success","data":{"orders":[{"id":1,"region":"cn","amount":120}],"total":1}}
```

配置默认读取 `~/.axi/axi.json`，**不会自动读取当前目录的 `axi.json`**。项目配置用 `AXI_CONFIG` 指定；相对 `.py` 路径以配置文件所在目录为基准。未指定 `name` 时，文件路径取文件名（不含扩展名），模块路径取最后一段作为工具组名。

### 3. 通过 Python 批量调用

沿用同一份 `AXI_CONFIG`，创建 `batch.py`：

```python
import json
from concurrent.futures import ThreadPoolExecutor

from axi import tool

query_orders = tool("orders/query_orders")


def region_total(region: str) -> dict:
    result = query_orders(region=region, limit=10)
    return {
        "region": region,
        "amount": sum(order["amount"] for order in result["orders"]),
    }


# 三个独立查询并发执行，仅将聚合结果输出给模型
with ThreadPoolExecutor(max_workers=3) as pool:
    totals = list(pool.map(region_total, ["cn", "jp", "us"]))

print(json.dumps(totals, ensure_ascii=False))
```

```bash
uv run --with axi-cli python batch.py
```

输出为 `[{"region": "cn", "amount": 120}, {"region": "jp", "amount": 80}, {"region": "us", "amount": 60}]`。

`tool("server/name")` 接受关键字参数，成功直接返回工具数据，失败抛出 `RuntimeError`，不返回 CLI 的 `status/data` 信封。首次调用自动发现 `nativeTools` 和已安装包的 `axi.native_tools` entry points；原生工具在当前进程执行，MCP 工具通过 daemon 执行。同一脚本可以获取多个工具句柄，将前一个工具的结果交给下一个工具。

批量处理前先通过 `describe` 查看输出示例或查阅工具契约；缺少返回结构时，可对只读工具做一次小规模调用确认。并发数按上游限流和工具状态约束设置，有顺序依赖的调用按顺序执行。

### 4. 导出为 MCP

```bash
# 全量工具：只暴露 search / grep / describe / run 四个元工具
axi mcp

# 直接暴露 orders 组中的工具
axi mcp --server orders

# 只允许发现和调用 orders 组，仍使用四个元工具
axi mcp --server orders --meta
```

无需再写一份 MCP server。

## 将已有 MCP 转为 CLI / PTC

将已有 server 的启动方式或 HTTP 端点加入当前配置的 `mcpServers`，例如：

```json
{
  "mcpServers": {
    "jina": {
      "command": "npx",
      "args": ["jina-mcp-tools"],
      "env": {"JINA_API_KEY": "your-key"}
    },
    "retrieval": {
      "url": "http://localhost:8000/mcp",
      "headers": {"Authorization": "Bearer your-token"}
    }
  }
}
```

stdio server 使用 `command / args / env`，HTTP server 使用 `url / headers`。用实际服务和凭据替换示例；工具组名取 `mcpServers` 的 key，无需等于包名。

```bash
axi grep '^jina/'
axi describe jina/jina_search
axi run jina/jina_search --query "python async" --count 3
```

同一个工具也能通过 `tool("jina/jina_search")(query="python async", count=3)` 在 Python 中调用，或与原生工具一起经 `axi mcp` 再导出。更改 MCP 配置后，停止旧 daemon，让下一次调用按新配置重新启动。

## 在 MCP 客户端中使用 axi

下面的客户端配置使用元工具模式，将多个工具组收敛到四个发现与执行入口：

```json
{
  "mcpServers": {
    "axi": {
      "command": "axi",
      "args": ["mcp"],
      "env": {"AXI_CONFIG": "/absolute/path/to/axi.json"}
    }
  }
}
```

客户端需能找到 `axi` 可执行文件；必要时使用其绝对路径。指定 `--server a,b` 时默认平铺，单组工具使用裸工具名，多组工具加 `server__` 前缀；`--flat / --meta` 可以覆盖默认模式。

HTTP 导出使用 `axi mcp --transport http --port 8321`，默认监听 `127.0.0.1`，端点为 `/mcp`。原生工具通过 `axi.env("API_KEY")` 读取变量时，优先使用当前请求的 `Axi-API-KEY` header，其次使用进程环境变量；CLI / stdio 下读取进程环境变量。

## 命令与输出

| 命令 | 用途 |
|---|---|
| `axi search <query> -k 5` | 按能力描述搜索工具，默认 BM25，可配置 embedding |
| `axi grep <pattern> -l 10` | 用正则匹配工具完整名和描述 |
| `axi list [server]` | 枚举工具组；可用逗号指定多组 |
| `axi describe <tool>` | 查看完整输入 schema 和可选输出示例；支持逗号分隔批量查看 |
| `axi run <tool> --key value` | 执行工具；复杂参数用 `-j '{"key":"value"}'` |
| `axi mcp` | 导出为 MCP server，支持 stdio / HTTP |
| `axi doctor` | 检查配置、工具来源、daemon、MCP 连接及 embedding 配置 |
| `axi daemon start / status / stop` | 管理或检查后台连接进程 |

工具命令输出 JSON。`axi run` 成功返回 `{"status":"success","data":...}`，失败返回 `{"status":"error","error":"..."}`；自动化处理要检查 `status`，工具执行失败不一定产生非零退出码。`daemon start / stop` 输出状态文本，`--help` 输出命令帮助。

`--key value` 按目标输入 schema 解析：字符串字段保留原文，其他字段尝试解析 JSON 数字、布尔值、数组和对象。嵌套数据或需要明确类型时，用 `--json / -j` 传完整 JSON 对象。

## 搜索与运行配置

`search` 默认使用 BM25 关键词检索，支持中英文分词；`grep` 使用正则，不调用 embedding。可在配置中添加：

```json
{
  "search": {
    "embedding": {"provider": "jina"}
  },
  "daemon": {
    "idleTimeoutMinutes": 30,
    "requestTimeout": 120
  }
}
```

- embedding 支持 `jina / openai`，密钥可分别从 `JINA_API_KEY / OPENAI_API_KEY` 读取；配置后在支持的索引上通过 RRF 融合 BM25 与向量检索。
- 当前 CLI 的原生工具使用本地 BM25 索引，MCP 工具使用 daemon 索引；结果按原生在前、MCP 在后合并，`-k / -l` 分别作用于两端，合并后可能超过指定数量。MCP 元工具模式使用合并索引，支持对两种来源统一做混合搜索。
- MCP 调用经 daemon 保持长连接，支持有状态 server。需要访问 daemon 的命令会自动启动它；默认空闲 30 分钟关闭。`status: starting` 表示正在初始化，`status: running` 表示已就绪。
- 每个配置文件路径对应独立 daemon，运行文件位于 `~/.axi/daemons/<hash>.sock / .pid / .log`。配置在进程启动时加载；MCP 配置修改后执行 `axi daemon stop`，已启动的 `axi mcp` 服务也需要重启。
- 单个 daemon 请求默认等待 120 秒；可用 `daemon.requestTimeout` 或环境变量 `AXI_REQUEST_TIMEOUT` 调整。

## Agent skills 与更多文档

仓库提供两个可供 Agent 加载的技能目录；复制到所用 Agent 支持的 skills 目录时，保留目录内的 `references/`：

- [axi-use](skills/axi-use/SKILL.md)：发现和调用已有工具，按任务选择 CLI 或 Python PTC。
- [axi-creator](skills/axi-creator/SKILL.md)：封装函数 / API、接入 MCP，以及打包和导出工具。

更多内容见 [使用指南](docs/guide.md)、[配置字段参考](docs/configuration.md)和[架构说明](docs/architecture.md)。命令参数以 `axi <command> --help` 为准。

## License

MIT
