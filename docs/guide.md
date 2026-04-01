# axi 使用指南

axi（Agent eXecution Interface）是 AI Agent 与外部系统之间的统一工具层。它将 MCP server 和 Python 函数统一为可搜索、可调用的 CLI 命令。

## 安装

```bash
uv pip install -e .
```

安装后 `axi` 命令即可在终端中使用。

---

## 快速开始

```bash
# 搜索工具
axi search "web"

# 查看工具详情
axi describe jina-mcp-tools/jina_search

# 执行工具
axi run jina-mcp-tools/jina_search --query "hello world" --count 3
```

---

## CLI 命令

所有命令输出统一为紧凑 JSON。

### axi list

列出所有 server 及其工具。

```bash
# 列出所有 server 及工具名
axi list

# 列出指定 server 的工具详情（含描述）
axi list jina-mcp-tools
```

**参数：**

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `server_name` | 只列出指定 server 的工具（位置参数） | 全部 |

**输出示例：**

`axi list`：

```json
[{"server":"jina-mcp-tools","tools":["jina_reader","jina_search"]},{"server":"retrieval","tools":["search_knowledge"]}]
```

`axi list jina-mcp-tools`：

```json
{"server":"jina-mcp-tools","tools":[{"name":"jina_reader","description":"Read and extract content from web page."},{"name":"jina_search","description":"Search the web."}]}
```

### axi search

搜索已注册的工具。默认使用 BM25 关键词搜索（bm25s + jieba 分词），支持中英文自然语言查询。如果在 `axi.json` 中配置了 Embedding，则自动启用混合搜索（BM25 + Embedding，通过 RRF 融合排序）。返回匹配工具的名称、描述、来源和相关性分数。

```bash
# BM25 关键词搜索（默认）
axi search "读取"

# 正则匹配
axi grep "read_.*"

# 限制返回数量
axi search "web" --top-k 5
```

**search 参数：**

| 参数 | 缩写 | 说明 | 默认值 |
|------|------|------|--------|
| `query` | - | 搜索关键词（位置参数） | 必填 |
| `--top-k` | `-k` | 返回结果数量 | 10 |

**grep 参数：**

| 参数 | 缩写 | 说明 | 默认值 |
|------|------|------|--------|
| `pattern` | - | 正则表达式（位置参数） | 必填 |
| `--top-k` | `-k` | 返回结果数量 | 10 |

**输出示例：**

```json
[{"name":"jina-mcp-tools/jina_reader","description":"Read and extract content from web page.","source":"mcp","score":0.82}]
```

**Embedding 搜索配置：**

在 `axi.json` 中添加 `search.embedding` 字段即可启用混合搜索：

```json
{
    "mcpServers": { ... },
    "search": {
        "embedding": {
            "provider": "jina",
            "apiKey": "jina_xxx",
            "model": "jina-embeddings-v3",
            "baseUrl": "https://api.jina.ai/v1"
        }
    }
}
```

| 字段 | 必填 | 说明 |
|------|------|------|
| `provider` | 是 | Embedding 提供商（`jina` / `openai`） |
| `apiKey` | 否 | API 密钥，省略时从环境变量读取（如 `JINA_API_KEY`、`OPENAI_API_KEY`） |
| `model` | 否 | 模型名称，各 provider 有默认值 |
| `baseUrl` | 否 | 自定义 API 端点 |

### axi describe

查看单个工具的完整元数据，包括 input_schema。

```bash
axi describe jina-mcp-tools/jina_search
```

**参数：**

| 参数 | 说明 |
|------|------|
| `tool_name` | 工具完整名称（位置参数），必填 |

**输出示例：**

```json
{"name":"jina_search","server":"jina-mcp-tools","description":"Search the web.","input_schema":{"type":"object","properties":{"query":{"type":"string","description":"Search query"},"count":{"type":"number","default":5}},"required":["query"]},"source":"mcp"}
```

### axi run

执行工具。支持两种参数传递方式。

**方式一：--key value 格式**

```bash
axi run jina-mcp-tools/jina_search --query "hello" --count 3
```

值会自动尝试 JSON 解析（数字、布尔值等），解析失败则作为字符串。

**方式二：--json 格式**

```bash
axi run jina-mcp-tools/jina_search -j '{"query": "hello", "count": 3}'
```

适合参数结构复杂或需要传递嵌套对象的场景。

**参数：**

| 参数 | 缩写 | 说明 |
|------|------|------|
| `tool_name` | - | 工具完整名称（位置参数），必填 |
| `--json` | `-j` | JSON 字符串格式的参数 |

**输出格式（统一信封）：**

```json
{"status":"success","data":"..."}
{"status":"error","error":"错误信息"}
```

---

## Daemon 模式

MCP 工具通过后台 daemon 进程维持长连接。daemon 保持所有 MCP server 的连接常驻内存，CLI 命令通过 Unix socket 与 daemon 通信，避免每次命令都重新连接。

这对需要保持状态的 MCP server（如 browser MCP，需要维持浏览器 session）至关重要。

### 管理命令

```bash
# 启动 daemon（后台运行）
axi daemon start

# 指定配置文件
axi daemon start --config /path/to/axi.json

# 查看状态
axi daemon status

# 停止
axi daemon stop
```

### 自动启动

执行 `axi search`、`axi describe`、`axi run` 时，如果 daemon 未运行且存在 `axi.json`，axi 会自动启动 daemon。无需手动管理。

### 工作原理

```
axi CLI ──(Unix socket ~/.axi/daemon.sock)──> axi daemon ──(stdio)──> MCP server A
                                                          ──(stdio)──> MCP server B
                                                          ──(stdio)──> MCP server C
```

- daemon 进程在后台常驻，PID 记录在 `~/.axi/daemon.pid`
- CLI 通过 Unix domain socket 发送 JSON 请求，daemon 返回 JSON 响应
- 原生 Python 工具不经过 daemon，直接在 CLI 进程内执行

---

## 工具来源

### MCP Server（通过 axi.json 配置）

在项目根目录创建 `axi.json`，MCP server 配置放在 `mcpServers` 字段下：

```json
{
    "mcpServers": {
        "jina-mcp-tools": {
            "command": "npx",
            "args": ["jina-mcp-tools"],
            "env": {
                "JINA_API_KEY": "your-api-key"
            }
        },
        "github": {
            "command": "npx",
            "args": ["@modelcontextprotocol/server-github"],
            "env": {
                "GITHUB_TOKEN": "your-token"
            }
        }
    },
    "nativeTools": [
        {"module": "my_project.tools"},
        {"module": "test/test_tool.py", "name": "test_tool"},
        {"module": "my_project.analytics", "name": "analytics"}
    ]
}
```

**顶层字段：**

| 字段 | 必填 | 说明 |
|------|------|------|
| `mcpServers` | 否 | MCP server 配置（对象） |
| `nativeTools` | 否 | 原生工具配置列表（对象数组） |

**mcpServers 内每个 server 的配置字段：**

| 字段 | 必填 | 说明 |
|------|------|------|
| key 名 | 是 | 作为工具命名空间（如 `jina-mcp-tools`） |
| `command` | 是 | 启动 MCP server 的命令 |
| `args` | 否 | 命令参数列表 |
| `env` | 否 | 环境变量 |

配置完成后 axi 自动发现所有 MCP 工具，无需额外操作。工具名格式为 `server/tool_name`。

### 原生 Python 工具（通过 @tool 装饰器）

在 Python 模块中用 `@tool` 装饰器注册工具，然后在 `axi.json` 的 `nativeTools` 中声明模块路径。

**nativeTools 配置字段：**

| 字段 | 必填 | 说明 |
|------|------|------|
| `module` | 是 | 模块路径。支持文件路径（`.py` 后缀，如 `test/test_tool.py`）和 Python 模块路径（如 `my_project.tools`） |
| `name` | 否 | 作为 server 名（命名空间）。省略时自动推导：文件路径取 stem（`test/test_tool.py` → `test_tool`），模块路径取最后一段（`my_project.tools` → `tools`） |

配置示例：

```json
{
    "nativeTools": [
        {"module": "my_project.tools"},
        {"module": "test/test_tool.py", "name": "test_tool"},
        {"module": "my_project.analytics", "name": "analytics"}
    ]
}
```

- `{"module": "my_project.tools"}` — name 省略，自动推导为 `tools`，工具调用格式为 `tools/query_orders`
- `{"module": "test/test_tool.py", "name": "test_tool"}` — 显式指定 name，工具调用格式为 `test_tool/some_tool`
- `{"module": "my_project.analytics", "name": "analytics"}` — 显式指定 name，工具调用格式为 `analytics/some_tool`

**工具定义示例：**

```python
from axi import tool

@tool(name="query_orders", description="按区域查询订单")
def query_orders(region: str, limit: int = 10) -> dict:
    return {"orders": [...], "total": 42}
```

装饰器自动从函数签名提取参数 schema：

- 类型映射：`str`→string, `int`→integer, `float`→number, `bool`→boolean, `list`→array, `dict`→object
- 无默认值的参数标记为 required
- 有默认值的参数记录 default

可选提供 `output_example`，帮助 Agent 在 PTC 场景下理解返回格式：

```python
@tool(
    name="query_orders",
    description="按区域查询订单",
    output_example={"orders": [{"id": 1, "region": "cn"}], "total": 1}
)
def query_orders(region: str, limit: int = 10) -> dict:
    ...
```

注册后工具同时具备 CLI 调用和 PTC 调用能力。

---

## PTC（Programmatic Tool Calling）

PTC 允许 Agent 写一段 Python 代码批量调用工具，在本地做数据过滤和聚合，避免反复 LLM round-trip。

```python
from axi import tool

# 获取工具的可调用对象
search = tool("jina-mcp-tools/jina_search")
reader = tool("jina-mcp-tools/jina_reader")

# 搜索（返回值格式取决于 MCP server，先试调一次确认）
results = search(query="python async", count=5)
print(results)  # jina_search 返回纯文本，需要自行解析
```

`tool("name")` 返回一个普通 Python 函数：
- 调用时传入关键字参数
- 成功返回 `data` 字段的值（可能是字符串、dict 或其他类型，取决于工具实现）
- 失败抛出 `RuntimeError`

### PTC 与 output 格式

- **原生工具**：如果提供了 `output_example`，可通过 `axi describe` 查看返回格式
- **MCP 工具**：MCP 协议不含 output schema，建议先 `axi run` 一次查看真实返回结构，再编写批量处理代码

---

## Agent 集成指南

axi 的设计遵循**渐进式披露**原则，Agent 按需获取信息，避免上下文窗口爆炸。

### 推荐工作流

```
1. axi search "<关键词>"         → 获取工具列表（轻量）
2. axi describe <tool_name>      → 获取完整 schema（按需）
3. axi run <tool_name> --params  → 执行
```

### Agent 使用示例

**场景：Agent 需要搜索网页内容**

```bash
# Step 1: 发现可用工具
$ axi search "web"
[{"name":"jina-mcp-tools/jina_reader","description":"Read and extract content from web page.","source":"mcp"},{"name":"jina-mcp-tools/jina_search","description":"Search the web.","source":"mcp"}]

# Step 2: 了解参数
$ axi describe jina-mcp-tools/jina_search
{"name":"jina_search","server":"jina-mcp-tools","description":"Search the web.","input_schema":{"type":"object","properties":{"query":{"type":"string","description":"Search query"},"count":{"type":"number","default":5}},"required":["query"]},"source":"mcp"}

# Step 3: 执行
$ axi run jina-mcp-tools/jina_search --query "python async tutorial" --count 3
{"status":"success","data":"..."}
```

**场景：Agent 需要批量处理数据（PTC）**

Agent 先探测返回格式，然后写脚本批量处理：

```bash
# 先试一次，看返回结构
$ axi run jina-mcp-tools/jina_search --query "test" --count 1
```

根据返回结构编写 PTC 脚本：

```python
import re
from axi import tool

search = tool("jina-mcp-tools/jina_search")
reader = tool("jina-mcp-tools/jina_reader")

# 搜索（jina_search 返回纯文本，需解析 URL）
results = search(query="python best practices", count=3)
urls = re.findall(r'URL Source: (https?://\S+)', results)

# 读取每个结果的完整内容
for url in urls[:2]:
    content = reader(url=url)
    print(content[:500])
    print("---")
```

### 输出约定

- 所有命令输出统一为紧凑 JSON（单行），方便 Agent 解析
- `axi run` 的返回统一为 `{"status":"success","data":...}` 或 `{"status":"error","error":"..."}` 信封格式
- 非零退出码表示错误（如工具不存在）
