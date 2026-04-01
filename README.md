# axi

Agent eXecution Interface — AI Agent 与外部系统之间的统一工具层。

通过 CLI 作为万能适配器，将 MCP server 和 Python 函数统一为可搜索、可描述、可调用的命令。Agent 无需猜测命令格式或解析人类可读输出，所有交互都是结构化 JSON。

## 核心理念

几乎所有主流 Agent 框架都把 bash 作为基础能力。axi 在这个"万能通道"之上建一层 Agent-native 的工具层：

- **渐进式披露** — `search → describe → run`，按需获取信息，不吃 context window
- **Agent-first 输出** — 统一紧凑 JSON，无表格、无颜色、无进度条
- **双来源统一** — MCP server 和原生 Python 工具，对 Agent 来说是同一套接口

## 安装

```bash
# 需要 Python 3.12+
uv pip install -e .
```

## 快速开始

```bash
# 搜索工具
axi search "web"

# 查看工具详情
axi describe jina/jina_search

# 执行工具
axi run jina/jina_search --query "hello world" --count 3
```

## 配置

在项目根目录创建 `axi.json`（参考 `axi.json.example`）：

```json
{
    "mcpServers": {
        "jina": {
            "command": "npx",
            "args": ["jina-mcp-tools"],
            "env": { "JINA_API_KEY": "your-key" }
        }
    },
    "nativeTools": [
        {"module": "my_project.tools"},
        {"module": "./scripts/tools.py", "name": "scripts"}
    ]
}
```

- **mcpServers** — MCP server 配置，key 名作为工具命名空间
- **nativeTools** — 原生 Python 工具，`module` 支持文件路径和模块路径，`name` 可选（省略则自动推导）

## CLI 命令

| 命令 | 说明 |
|------|------|
| `axi list [server]` | 列出所有 server 及工具 |
| `axi search <query>` | 混合搜索工具（BM25 + Embedding，支持 `--top-k`） |
| `axi grep <pattern>` | 正则表达式搜索工具（支持 `--top-k`） |
| `axi describe <tool>` | 查看工具完整 schema |
| `axi run <tool> --key value` | 执行工具（也支持 `-j '{...}'` 传 JSON） |
| `axi daemon start\|status\|stop` | 管理 daemon 进程 |

所有输出统一为紧凑 JSON。`axi run` 返回统一信封：

```json
{"status": "success", "data": "..."}
{"status": "error", "error": "错误信息"}
```

## 注册原生工具

```python
from axi import tool

@tool(name="query_orders", description="按区域查询订单")
def query_orders(region: str, limit: int = 10) -> dict:
    return {"orders": [...], "total": 42}
```

装饰器自动从函数签名提取参数 schema。注册后同时获得 CLI 调用和 PTC 调用能力。

## PTC（Programmatic Tool Calling）

Agent 可以写 Python 代码批量调用工具，在本地做数据过滤和聚合，避免反复 LLM round-trip：

```python
from axi import tool

search = tool("jina/jina_search")
results = search(query="python async", count=5)
```

## Daemon 模式

MCP 工具通过后台 daemon 长连接执行，支持有状态 MCP server（如 browser MCP）。执行 `axi search/describe/run` 时自动启动 daemon，无需手动管理。

```
axi CLI ──(Unix socket)──> daemon ──(stdio)──> MCP server A
                                   ──(stdio)──> MCP server B
```

## 技术栈

Python 3.12+ / [Typer](https://typer.tiangolo.com/) / [Pydantic](https://docs.pydantic.dev/) / [MCP SDK](https://github.com/modelcontextprotocol/python-sdk)

## License

MIT
