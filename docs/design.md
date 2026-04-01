# axi 设计文档

## 定位

axi（Agent eXecution Interface）是 AI Agent 与外部系统之间的统一工具层。

核心洞察：几乎所有主流 Agent 框架（Claude Code、Cursor、Devin、OpenHands 等）都把 bash/shell 作为基础能力。CLI 本质上是一个通用的、无需额外适配的 Agent-to-System 协议层——不需要写 MCP server，不需要 API wrapper，装个命令行工具就能用。

axi 在 bash 这个"万能通道"之上，建一层 Agent-native 的协议和工具层，让 Agent 调用外部系统时，不再是"盲猜命令 → 解析人类可读输出 → 祈祷没出错"，而是有一套结构化的、可发现的、权限可控的交互方式。

### 与 MCP 的关系

MCP 解决的是"Agent 怎么调用工具"的协议问题，但它需要每个系统都写一个 MCP server。axi 走的是另一条路——CLI 作为万能适配层，不需要目标系统做任何改造，同时能直接消费 MCP 生态中已有的工具定义。

## 设计原则

### 渐进式披露（Progressive Disclosure）

Agent 不需要一次性知道所有工具。当工具数量庞大时，把所有 tool definition 塞进 system prompt 会吃掉大量 context window。axi 提供按需逐层获取的机制：

```
axi search "数据库"          → 工具名 + 一句话描述（最轻量）
axi describe query_orders    → 完整 input_schema + 用法（按需展开）
axi run query_orders ...     → 执行
```

### Agent-first 输出

传统 CLI 的输出是为人类设计的（表格、颜色、进度条），Agent 解析起来很脆弱。axi 的所有输出统一为紧凑 JSON，无需额外 flag。

`axi run` 的统一输出信封：

```json
{"status": "success", "data": {...}}
{"status": "error", "error": "错误信息"}
```

## 核心功能

### 功能一：MCP → axi 直接转换

MCP server 里的 tools 自动变成 axi 可管理的工具。通过 `axi.json` 配置文件管理：

```json
// axi.json
{
    "mcpServers": {
        "jina-mcp-tools": {
            "command": "npx",
            "args": ["jina-mcp-tools"],
            "env": {
                "JINA_API_KEY": "xxx"
            }
        },
        "github": {
            "command": "npx",
            "args": ["@modelcontextprotocol/server-github"],
            "env": {
                "GITHUB_TOKEN": "xxx"
            }
        }
    },
    "nativeTools": [
        {"module": "my_project.tools"},
        {"module": "./scripts/tools.py", "name": "scripts"}
    ]
}
```

MCP server 的 key 名天然作为命名空间，自动隔离不同来源的工具：

```bash
axi run jina-mcp-tools/read_url --url "https://example.com"
axi run github/list_repos --owner "anthropics"
```

### 功能二：原生 Python 注册（跳过 MCP）

不是所有东西都要先包成 MCP server 再转。如果已经有一个 Python 函数、一个 REST API、一段数据库查询逻辑，应该能直接注册为 axi 工具：

```python
from axi import tool

@tool(name="query_orders", description="按区域查询订单")
def query_orders(region: str, limit: int = 10) -> dict:
    return db.execute("SELECT * FROM orders WHERE region=%s LIMIT %s", [region, limit])
```

装饰器从函数签名 + type hints 自动提取 input_schema。注册后同时获得 CLI 调用和 PTC 调用的能力。

#### nativeTools 配置格式

`nativeTools` 只支持对象格式，每个条目包含 `module`（必填）和 `name`（可选）：

```json
"nativeTools": [
    {"module": "my_project.tools"},
    {"module": "./scripts/tools.py", "name": "scripts"}
]
```

- **module**：支持两种形式
  - Python 模块路径：如 `"my_project.tools"`
  - 文件路径：如 `"./scripts/tools.py"`
- **name**（可选）：作为 server 名，用于工具调用时的命名空间前缀。省略时自动推导：
  - 文件路径：取 stem（如 `./scripts/tools.py` → `tools`）
  - 模块路径：取最后一段（如 `my_project.tools` → `tools`）

原生工具的调用格式与 MCP 工具一致，都是 `server/tool_name`：

```bash
axi run tools/query_orders --region cn
```

### 两条路径统一出口

不管工具来源是什么，进入 axi 之后对 Agent 来说都是统一的——同一套 search、同一套 run、同一套 PTC 函数接口。

## 执行模式

### CLI 直接调用

最基础的形态，人或 Agent 在终端里直接调用：

```bash
axi run <tool_name> --param1 value1 --param2 value2
```

### PTC 批量编程（Programmatic Tool Calling）

与其让 Agent 每次调用一个工具都走一次完整的 LLM round-trip（发 JSON → 等响应 → 再发 JSON），不如让 Agent 写一段代码，在代码里直接调用多个工具、做数据过滤和聚合，最终只把精简的结果返回给 LLM。

```python
from axi import tool

db = tool("query_database")
result = await db(sql="SELECT * FROM orders")
# 在代码里直接过滤、聚合，不回传 LLM
```

底层执行方式不是重点，直接用 Python 包装执行终端命令即可。

### 工具搜索

```bash
axi search "数据库查询"       # BM25 关键词搜索（默认）
axi grep "query_.*"            # 正则精确匹配
```

搜索策略：
- **BM25**（默认）：基于 bm25s + jieba 分词的关键词相关性排序，支持中英文，适合自然语言查询
- **Embedding**（可选）：通过 Jina/OpenAI 等 provider 进行语义搜索（LangChain 接入），在 `axi.json` 中配置 `search.embedding` 启用。启用后与 BM25 通过 RRF（Reciprocal Rank Fusion）混合排序，分数归一化到 0-1
- **正则**：精确匹配，适合 Agent 知道部分名称的场景

### 工具描述

```bash
axi describe <tool_name>  # 返回 name / description / input_schema
```
