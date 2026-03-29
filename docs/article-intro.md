# axi：让 AI Agent 像人一样用工具

## Agent 调工具，为什么这么难？

2024 年以来，AI Agent 的能力突飞猛进。从 Claude Code 到 Cursor，从 Devin 到 OpenHands，这些 Agent 已经可以写代码、改 bug、做部署。但有一个问题始终横亘在 Agent 和"真正好用"之间——**Agent 怎么调用外部工具？**

目前主流有两条路，但都不太好走。

**第一条路：MCP（Model Context Protocol）**

Anthropic 提出的 MCP 是一套标准化协议，让 Agent 通过统一接口调用工具。思路很好，但有两个现实问题：

第一，**每个系统都要写一个 MCP server**。想用 Jira？写个 MCP server。想查数据库？再写一个。想调内部 API？又是一个。MCP 生态确实在快速增长，但覆盖率远远不够。你的内部系统、私有工具、临时脚本，大概率没有现成的 MCP server。

第二，**工具数量爆炸吃掉 context window**。MCP 的标准用法是把所有 tool definition 注入 system prompt——名称、描述、完整参数 schema，一个工具就是一段 JSON。问题是，现实中一个 MCP server 动辄就有几十个工具。GitHub MCP server 有 30+ 个工具，Jira 也差不多。你接了 3 个 MCP server，可能就是 100 个工具的 schema 全量注入，几千甚至上万 token 就这么没了——Agent 还没开始干活呢。更关键的是，Agent 大多数时候只需要其中 2-3 个工具，剩下 97 个纯属浪费。

**第二条路：直接用 bash**

几乎所有主流 Agent 框架都把 bash/shell 作为基础能力。这是一条"什么都能干"的路——装个命令行工具就能用，不需要写 wrapper，不需要适配协议。

但 bash 的输出是给人看的。表格、颜色代码、进度条、交互式提示……Agent 要从这堆人类可读输出中解析出结构化数据，基本是在"盲猜 + 祈祷"。一个命令升级了版本换了输出格式，之前写的解析逻辑就全废了。

**被忽视的洞察**

仔细想想，这两条路其实有一个交汇点：**CLI 本身就是一个通用的 Agent-to-System 协议层**。

几乎所有系统都提供 CLI 工具（或者可以很容易地包一个），CLI 不需要目标系统做任何改造，且已经有成熟的参数传递、错误码、管道等机制。bash 差的不是"能力"，而是"Agent 友好性"。

而且反过来看，**bash 是所有 Agent 框架的最大公约数**。不管是 Claude Code、Cursor 还是 Devin，不管底层用什么语言、什么框架，它们都能执行 shell 命令。一个基于 CLI 的工具层，天然兼容所有 Agent——不需要写 server，不需要写 client，不需要引 SDK。

如果我们在 bash 这个"万能通道"之上，建一层 Agent-native 的结构化协议——既保留 CLI 的万能适配能力，又提供 MCP 级别的结构化交互——会怎样？

这就是 **axi** 要做的事。

---

## axi 是什么

**axi**（Agent eXecution Interface）是 AI Agent 与外部系统之间的**统一工具层**。

一句话概括：**通过 CLI 作为万能适配器，让任何工具变成 Agent 可发现、可搜索、可编程调用的命令。**

和 MCP 相比，axi 最大的不同是**极其轻量**：

- **不需要 server** — 不用为每个系统写一个 MCP server
- **不需要 client** — 不用在 Agent 框架里集成 MCP client SDK
- **只需要 bash** — 你的 Agent 能执行 shell 命令就行

这意味着 axi 对 Agent 框架是**零侵入**的。Claude Code、Cursor、Devin、OpenHands，甚至一个最简单的"LLM + bash 执行器"——只要你的 Agent 能跑 bash 命令，就能用 axi。不需要适配任何协议，不需要引入任何 SDK，`pip install` 之后直接用。

同时 axi 也不浪费 MCP 生态的成果。它支持两种工具来源：

- **MCP server**：已有的 MCP 生态直接消费，一行配置变 CLI 命令
- **原生 Python 函数**：加个装饰器就能注册，不用写 MCP server

不管工具从哪来，进入 axi 之后对 Agent 来说都是统一的——同一套搜索、同一套执行、同一套输出格式。

```
AI Agent (bash)
    ↓
axi CLI ── search / describe / run
    ├── 原生工具 → 进程内直接执行
    └── MCP 工具 → daemon (长连接) → MCP server
```

接下来逐一展开 axi 的核心特性。

---

## 特性一：MCP → CLI，零改造转换

> 如果你不熟悉 MCP：它是 Anthropic 提出的开放协议，定义了 AI Agent 和外部工具之间的通信标准。一个 MCP server 暴露若干 tool，每个 tool 有名称、描述、参数 schema。Agent 通过 JSON 格式调用这些 tool。

MCP 生态已经有大量现成的 server——GitHub、Jira、Slack、浏览器自动化、各种 API 封装。axi 可以**直接消费这些 MCP server**，不需要任何改造，只需要在配置文件里声明一下。

### 配置

在项目根目录创建 `axi.json`：

```json
{
    "mcpServers": {
        "jina": {
            "command": "npx",
            "args": ["jina-mcp-tools"],
            "env": { "JINA_API_KEY": "your-key" }
        },
        "github": {
            "command": "npx",
            "args": ["@modelcontextprotocol/server-github"],
            "env": { "GITHUB_TOKEN": "your-token" }
        }
    }
}
```

配完之后，这些 MCP server 里的所有 tool 自动变成 axi 可管理的命令。server 的 key 名（`jina`、`github`）天然成为命名空间：

```bash
axi run jina/jina_search --query "hello world"
axi run github/list_repos --owner "anthropics"
```

不同来源的同名工具不会冲突，命名空间天然隔离。

### Daemon 长连接

MCP 工具的执行不是"每次命令都重新连接 MCP server"——那太慢了。axi 通过后台 **daemon 进程**维持所有 MCP server 的长连接。

```
axi CLI ──(Unix socket)──> daemon ──(stdio)──> Jina MCP server
                                   ──(stdio)──> GitHub MCP server
                                   ──(stdio)──> Browser MCP server
```

daemon 的存在对用户是透明的：

- 第一次执行 `axi search` / `axi run` 时，如果 daemon 没启动，**自动启动**
- daemon 在后台常驻，PID 记录在 `~/.axi/daemon.pid`
- CLI 通过 Unix domain socket 和 daemon 通信，延迟极低
- 需要时 `axi daemon stop` 手动停止

这对**有状态的 MCP server** 至关重要。比如 browser MCP 需要维持浏览器 session，如果每次命令都重启连接，session 就丢了。daemon 让这些有状态连接可以跨多次命令持续存活。

---

## 特性二：@tool 原生注册，跳过 MCP

不是所有东西都要先包成 MCP server 再用。如果你已经有一个 Python 函数、一段数据库查询、一个内部 API 调用，应该能**直接注册为 axi 工具**，零额外开销。

```python
from axi import tool

@tool(name="query_orders", description="按区域查询订单")
def query_orders(region: str, limit: int = 10) -> dict:
    return db.execute(
        "SELECT * FROM orders WHERE region=%s LIMIT %s",
        [region, limit]
    )
```

**就这样。** 装饰器自动从函数签名 + type hints 提取参数 schema：

- `str` → `string`，`int` → `integer`，`float` → `number`，`bool` → `boolean`
- 无默认值 → `required`
- 有默认值 → 记录 `default`

注册后立刻获得 CLI 调用能力：

```bash
axi run tools/query_orders --region cn --limit 20
```

然后在 `axi.json` 中声明模块路径：

```json
{
    "nativeTools": [
        {"module": "my_project.tools"},
        {"module": "./scripts/tools.py", "name": "scripts"}
    ]
}
```

`module` 支持 Python 模块路径和文件路径两种形式。`name` 可选，省略时自动推导（文件取 stem，模块取最后一段）。

### 对比：传统 MCP server vs axi @tool

写一个 MCP server 注册同样的工具，你需要：定义 server、注册 handler、写参数 schema、处理连接生命周期……几十行代码起步。

axi 的 `@tool`？**三行搞定**：装饰器 + 函数签名 + 返回值。Schema 自动提取，CLI 自动生成，无需手写。

而且原生工具**在进程内直接执行**，不经过 daemon，没有 socket 通信开销。适合轻量级、高频调用的场景。

---

## 特性三：渐进式披露

回到开头提到的痛点——工具数量爆炸吃 context window。

来看一个真实例子。GitHub MCP server 提供了 30+ 个工具：`create_issue`、`list_repos`、`create_pull_request`、`get_file_contents`、`search_code`……每个工具都有名称、描述、完整参数 schema。按传统做法，这 30 个工具的 definition 全量注入 system prompt，轻松吃掉 5000+ token。

再加上 Jira MCP（20+ 工具）、Slack MCP（15+ 工具）、一个自定义的内部工具集（10+ 工具）——你的 Agent 还没开口说话，system prompt 里就已经塞了 70 多个工具的 schema，占掉上万 token。

但实际上呢？用户说"帮我在 GitHub 上创建一个 issue"，Agent 只需要 `github/create_issue` **这一个工具**。其他 69 个工具的 schema 全是噪音。

axi 走的是另一条路——**渐进式披露（Progressive Disclosure）**。不预注入任何工具 schema，Agent 使用时才去获取：

### 第一层：search — 我有什么工具？

Agent 需要操作 GitHub？先搜：

```bash
$ axi search "issue"
[
  {"name": "github/create_issue", "description": "Create a new issue in a GitHub repository.", "source": "mcp"},
  {"name": "github/list_issues", "description": "List issues in a GitHub repository.", "source": "mcp"},
  {"name": "github/update_issue", "description": "Update an existing issue.", "source": "mcp"}
]
```

只返回名称 + 一句话描述。70 个工具搜出 3 个相关的，几十 token 搞定。

### 第二层：describe — 这个工具怎么用？

锁定目标后，再获取完整 schema：

```bash
$ axi describe github/create_issue
{
  "name": "create_issue",
  "server": "github",
  "description": "Create a new issue in a GitHub repository.",
  "input_schema": {
    "type": "object",
    "properties": {
      "owner": {"type": "string", "description": "Repository owner"},
      "repo": {"type": "string", "description": "Repository name"},
      "title": {"type": "string", "description": "Issue title"},
      "body": {"type": "string", "description": "Issue body"}
    },
    "required": ["owner", "repo", "title"]
  },
  "source": "mcp"
}
```

只获取这一个工具的 schema，不是 30 个全量注入。

### 第三层：run — 执行

```bash
$ axi run github/create_issue --owner "myorg" --repo "myapp" --title "Fix login bug"
{"status": "success", "data": {"id": 42, "url": "https://..."}}
```

### 算一笔账

| 方式 | 工具数量 | token 消耗 | 时机 |
|------|---------|-----------|------|
| 传统全量注入 | 70 个全部注入 | ~10000+ token | 每次对话都占 |
| axi 渐进式 | search 3 个 + describe 1 个 | ~200 token | 仅在需要时 |

**50 倍的差距**。而且传统方式是每次对话都固定占用，axi 是按需获取、用完即走。

这个设计的价值随工具数量增长而放大。10 个工具可能感受不明显，50 个开始难受，100 个以上就是质的区别。当你的 Agent 需要对接多个系统、工具集越来越大的时候，渐进式披露不是锦上添花，而是**必需品**。

---

## 特性四：PTC — Programmatic Tool Calling

这是 axi 最有意思的设计。

### 传统 Tool Calling 的问题

目前主流 Agent 框架的 tool calling 流程是这样的：

```
Agent 思考 → 决定调用工具 A
    → 生成 tool_call JSON → 发给 runtime
    → runtime 执行工具 A → 返回结果给 LLM
Agent 思考 → 决定调用工具 B
    → 生成 tool_call JSON → 发给 runtime
    → runtime 执行工具 B → 返回结果给 LLM
Agent 思考 → 决定调用工具 C
    → ...
```

每一次工具调用都是一个完整的 **LLM round-trip**：Agent 生成调用请求 → 等待执行 → 结果返回 LLM → LLM 再思考下一步。

如果一个任务需要调用 5 个工具？5 次 round-trip。10 个？10 次。每次都要等 LLM 生成 + 推理，**慢且贵**。

更关键的是，很多时候中间步骤的"思考"其实很简单——"搜索结果里有 3 个 URL，挨个读一遍"。这种逻辑让 LLM 来做，纯属浪费。

### PTC 的解法

PTC（Programmatic Tool Calling）的思路是：**不要每次调用都回 LLM，让 Agent 写一段代码，在代码里直接调用多个工具。**

```python
from axi import tool

# 获取工具的可调用对象
search = tool("jina/jina_search")
reader = tool("jina/jina_reader")

# 搜索
results = search(query="python best practices", count=5)

# 从结果中提取 URL（本地处理，不回 LLM）
import re
urls = re.findall(r'URL Source: (https?://\S+)', results)

# 批量读取每个页面（本地循环，不回 LLM）
for url in urls[:3]:
    content = reader(url=url)
    print(content[:500])
    print("---")
```

`tool("name")` 返回一个普通 Python 函数。调用时传关键字参数，成功返回结果，失败抛 `RuntimeError`。就这么简单。

### 对比：传统方式 vs PTC

**传统方式**（假设搜索 + 读取 3 个页面）：

```
Round 1: Agent → "我要搜索" → tool_call → 搜索结果返回 LLM
Round 2: Agent → "结果里有这些 URL，我要读第一个" → tool_call → 内容返回 LLM
Round 3: Agent → "读第二个" → tool_call → 内容返回 LLM
Round 4: Agent → "读第三个" → tool_call → 内容返回 LLM
Round 5: Agent → "综合这些内容，总结一下"
```

5 次 LLM round-trip。中间那 3 次"读第 N 个"纯属机械操作，LLM 的参与毫无价值。

**PTC 方式**：

```
Round 1: Agent → "我写一段代码来搜索并读取内容"
         → 执行上面那段 Python 代码
         → 搜索 + 3 次读取全在代码里完成
         → 精简结果返回 LLM
Round 2: Agent → "综合这些内容，总结一下"
```

2 次 round-trip。中间的机械操作全在代码里完成，**不经过 LLM**。

### 为什么这很重要

- **更快**：减少 LLM round-trip 次数，每次 round-trip 都是秒级延迟
- **更省**：更少的 token 消耗（中间结果不用全量传给 LLM）
- **更灵活**：在代码里你可以用循环、条件判断、数据聚合……比 JSON tool_call 表达力强得多
- **更可控**：Agent 在本地过滤数据后只把精简结果返回 LLM，而不是把原始数据全部扔回去

PTC 的核心洞察是：**不是所有工具调用都值得一次 LLM round-trip。机械性的批量操作，让代码来做就好。**

而 axi 的 `tool()` 函数让 PTC 的实现变得极其自然——不管底层是 MCP 工具还是原生 Python 函数，`tool("name")` 统一返回可调用对象，Agent 写的代码不需要关心工具来源。

---

## 特性五：Agent-first 输出

传统 CLI 的输出是为人类设计的：

```
┌────────┬──────────┬──────────────────┐
│ Name   │ Status   │ Description      │
├────────┼──────────┼──────────────────┤
│ task-1 │ ✅ Done  │ Implement auth   │
│ task-2 │ 🔄 WIP  │ Add tests        │
└────────┴──────────┴──────────────────┘
```

好看吗？好看。Agent 能解析吗？不好说。下个版本表格格式变了呢？更不好说。

axi 的所有输出统一为**紧凑 JSON**：

```json
[{"name":"task-1","status":"done","description":"Implement auth"},{"name":"task-2","status":"wip","description":"Add tests"}]
```

没有表格，没有颜色代码，没有 emoji，没有进度条。**一行 JSON，`json.loads()` 一下就是结构化数据**。

`axi run` 的返回还有统一信封格式：

```json
{"status": "success", "data": {...}}
{"status": "error", "error": "工具不存在: foo/bar"}
```

Agent 不需要猜"这次执行成功了吗？"——看 `status` 字段就行。配合非零退出码，错误处理变得确定性十足。

这看起来是个小事，但对 Agent 的可靠性影响巨大。当你的 Agent 每天要调用上百次工具，输出格式的确定性直接决定了整个系统的稳定性。

---

## 架构亮点速览

除了上面的核心特性，axi 在实现上还有几个值得一提的设计：

### @tool 的双重身份

`tool` 这个函数有两种用法，取决于你怎么调用它：

```python
# 用法一：装饰器 — 注册一个原生工具
@tool(name="query_orders", description="查询订单")
def query_orders(region: str) -> dict:
    ...

# 用法二：函数调用 — 获取一个工具的可调用对象（PTC）
query = tool("query_orders")
result = query(region="cn")
```

同一个 API，既是注册入口又是运行时获取入口。没有 `register_tool()` / `get_tool()` 两套函数，概念模型极简。

### 搜索可插拔

当前搜索是子串匹配 + 正则，通过统一接口调用。未来可以在同一接口下扩展 BM25（关键词相关性排序）甚至 embedding（语义搜索），对上层无感。

```bash
# 当前：子串匹配
axi search "数据库"

# 当前：正则
axi search --regex "query_.*"

# 未来（接口不变）：BM25、embedding...
```

### 命名空间隔离

工具名天然带命名空间，不同来源的同名工具不会冲突：

```
jina/search        ← Jina MCP server 的 search
github/search      ← GitHub MCP server 的 search
my_tools/search    ← 自己写的原生 search
```

多个 MCP server + 多个原生模块可以自由组合，不用担心命名冲突。

### 参数智能解析

`axi run` 支持两种参数格式，适应不同场景：

```bash
# 简单场景：--key value
axi run jina/jina_search --query "hello" --count 3

# 复杂场景：-j JSON
axi run some_tool -j '{"nested": {"key": "value"}, "list": [1, 2, 3]}'
```

`--key value` 格式会自动尝试 JSON 解析——`3` 变数字，`true` 变布尔，解析失败则作为字符串。简单场景零摩擦，复杂场景有兜底。

---

## 适合什么场景？

- **你在构建 AI Agent**，需要一套结构化的工具调用层，而不是让 Agent 去猜 bash 输出格式
- **你想复用 MCP 生态**，但不想在每个 Agent 框架里单独集成 MCP client
- **你有内部 Python 工具**，想快速暴露给 Agent 使用，不想写 MCP server
- **你的 Agent 需要批量调用工具**，PTC 模式可以显著减少 LLM round-trip
- **你的工具集很大**，渐进式披露避免 context window 爆炸

---

## 当前状态与未来方向

axi 目前处于早期开发阶段，核心功能已经实现：

- MCP server 导入与管理
- 原生 Python 工具注册
- daemon 长连接模式
- CLI 全套命令（list / search / describe / run）
- PTC 编程调用

未来计划中的方向：

- **搜索增强**：BM25 关键词排序、embedding 语义搜索
- **权限模型**：工具级别的访问控制
- **流式输出**：支持长时间运行工具的流式返回
- **配置热加载**：无需重启 daemon 即可更新工具集

---

**技术栈**：Python 3.12+ / Typer / Pydantic / MCP SDK

如果你对 axi 感兴趣，欢迎关注项目进展，也欢迎参与讨论和贡献。
