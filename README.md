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
# 需要 Python 3.12+, uv
uv sync
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
        },
        "retrieval": {
            "url": "http://localhost:8000/mcp"
        }
    },
    "nativeTools": [
        {"module": "my_project.tools"},
        {"module": "./scripts/tools.py", "name": "scripts"}
    ],
    "search": {
        "embedding": {
            "provider": "jina"
        }
    },
    "daemon": {
        "idleTimeoutMinutes": 30
    }
}
```

- **mcpServers** — MCP server 配置，key 名作为工具命名空间。支持 `command`（本地进程）和 `url`（HTTP streaming）两种模式
- **nativeTools** — 原生 Python 工具，`module` 支持文件路径和模块路径，`name` 可选（省略则自动推导）
- **search** — 搜索配置，`embedding` 段启用语义搜索（支持 Jina/OpenAI）
- **daemon** — daemon 进程配置，如 idle 超时时间

完整配置参考见 [docs/configuration.md](docs/configuration.md)。

## CLI 命令

| 命令 | 说明 |
|------|------|
| `axi list [server]` | 列出所有 server 及工具 |
| `axi search <query>` | 混合搜索工具（BM25 + Embedding，支持 `--top-k/-k`） |
| `axi grep <pattern>` | 正则表达式搜索工具（支持 `--limit/-l`） |
| `axi describe <tool>` | 查看工具完整 schema |
| `axi run <tool> --key value` | 执行工具（也支持 `-j '{...}'` 传 JSON） |
| `axi daemon start` | 手动启动 daemon（通常无需手动，CLI 会自动拉起） |
| `axi daemon status` | 查看 daemon 状态（PID、运行时长、空闲时长、工具数量等） |
| `axi daemon stop` | 手动停止 daemon |

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

## 搜索

axi 提供两种搜索方式：

- **`axi search`** — 混合搜索，默认 BM25 关键词搜索（bm25s + jieba 分词，支持中英文）。配置 `search.embedding` 后启用 BM25 + Embedding 混合搜索（RRF 融合排序，分数归一化 0-1）
- **`axi grep`** — 正则表达式搜索，按工具名和描述匹配

搜索结果包含 `score` 字段，便于 Agent 判断相关性。

## Daemon 模式

MCP 工具通过后台 daemon 长连接执行，支持有状态 MCP server（如 browser MCP）。

```
axi CLI ──(Unix socket)──> daemon ──(stdio)──> MCP server A
                                   ──(stdio)──> MCP server B
```

### 自动管理

执行 `axi search`、`describe`、`run` 等命令时，CLI 会自动检测 daemon 是否运行，未运行则自动拉起。大多数情况下无需手动管理。

### 生命周期

| 阶段 | 行为 |
|------|------|
| **启动** | 加载 `axi.json` → 连接所有 MCP server → 创建 Unix socket → 写入 PID 文件 → 启动 idle watchdog |
| **运行** | 通过 `~/.axi/daemon.sock` 监听请求，路由到对应 MCP server 执行 |
| **空闲关闭** | 默认 30 分钟无活动自动关闭（每 60 秒检查一次；`status` 和 `shutdown` 请求不重置计时器） |
| **手动关闭** | `axi daemon stop` 发送关闭指令，daemon 优雅退出 |
| **信号关闭** | 收到 SIGTERM / SIGINT 时优雅关闭（清理 socket 和 PID 文件） |

空闲超时可通过 `axi.json` 的 `daemon.idleTimeoutMinutes` 配置：

```json
{ "daemon": { "idleTimeoutMinutes": 60 } }
```

### 手动管理

```bash
axi daemon start     # 手动启动（通常不需要）
axi daemon status    # 查看状态
axi daemon stop      # 手动停止
```

`axi daemon status` 输出示例：

```json
{
  "status": "running",
  "pid": 12345,
  "uptime_seconds": 1800,
  "idle_seconds": 120,
  "idle_timeout_seconds": 1800,
  "idle_remaining_seconds": 1680,
  "server_tools": { "jina": 5, "browser": 3 },
  "native_tools": 2
}
```

### 文件位置

daemon 运行时文件位于 `~/.axi/`：

| 文件 | 说明 |
|------|------|
| `daemon.sock` | Unix socket，CLI 与 daemon 的通信通道 |
| `daemon.pid` | daemon 进程 PID，用于检测是否存活 |
| `daemon.log` | daemon 启动和错误日志 |

## 技术栈

Python 3.12+ / [Typer](https://typer.tiangolo.com/) / [Pydantic](https://docs.pydantic.dev/) / [MCP SDK](https://github.com/modelcontextprotocol/python-sdk) / [bm25s](https://github.com/xhluca/bm25s) + [jieba](https://github.com/fxsjy/jieba) / [LangChain](https://python.langchain.com/)（Embedding）

## License

MIT
