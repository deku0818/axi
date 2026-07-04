---
name: axi-use
description: 通过 `axi` CLI（或在 Python 中使用 `from axi import tool`）发现并调用工具。当任务需要执行外部工具（当前拥有<changeme>）请使用此skill。核心工作流程为：`axi search <query>` → `axi describe <tool>` → `axi run <tool> --key value`；当任务涉及多次调用之间的循环、聚合或后处理时，请优先使用 Python 进行处理。
---

# axi — Agent 使用手册

axi 是当前环境里的工具调用层。有工具需求时，**先 `axi search`，再 `axi describe`，最后 `axi run`**，不要去翻代码或自己实现。

## 何时用

- 任务需要外部能力：web 搜索、知识库检索、注册过的 Python 函数、任何 MCP server 暴露的工具
- 用户让你"调用某工具 / 搜索某工具 / 查某工具怎么用"

工具可以来自三种渠道（对使用者透明，直接 `axi search` 就能找到）：`axi.json` 的 `mcpServers` / `nativeTools`，或 Python 包通过 entry_points 自动注册。配置文件位置由 `AXI_CONFIG` 环境变量指定，缺省 `~/.axi/axi.json`——**不会从当前目录自动发现**，项目级配置需要 `export AXI_CONFIG=/path/to/axi.json`。没有配置文件也不影响使用。

## 三步工作流

### 1. 发现工具 — `axi search` 或 `axi grep`

两个命令覆盖两种场景，**按你当前知道什么来选**：

| 你掌握的线索 | 用哪个 | 为什么 |
|---|---|---|
| 只有意图 / 能力描述（"web 搜索"、"查订单"） | `axi search` | BM25 + embedding 混合，支持中英文自然语言语义匹配 |
| 已知工具名或 server 名的片段 / 模式 | `axi grep` | 正则直匹，精确、无语义噪声 |
| 想看某个 server 下所有工具 | `axi list [server]` | 纯枚举，不做匹配（最后查找不到的兜底手段） |

```bash
axi search "web" --top-k 3
# [{"name":"jina/jina_search","description":"Search the web. ...","source":"mcp"},
#  {"name":"jina/jina_reader","description":"Read and extract content from web page.","source":"mcp"}]
# 结果按相关性排序（越靠前越相关），不含分数

axi grep "^jina/" --limit 5
# 精确列出 jina server 下所有工具

axi list jina
# [{"server":"jina","tools":["jina_reader","jina_search"]}]
```

### 2. 查看参数 — `axi describe`

拿到候选后，用完整名（`server/tool` 或原生工具的短名）查 schema：

```bash
axi describe jina/jina_search
```

返回：

```json
{"name":"jina_search","server":"jina","description":"...",
 "input_schema":{"type":"object",
   "properties":{"query":{"type":"string","minLength":1},
                 "count":{"type":"number","default":5},
                 "siteFilter":{"type":"string"}},
   "required":["query"]},
 "source":"mcp"}
```

**只看 `input_schema.required` 就知道必传什么**；可选参数用默认值即可。

### 3. 执行 — `axi run`

两种传参方式，**优先用 `--key value`**：

```bash
# 推荐：键值对，自动 JSON 解析数字 / 布尔 / JSON 字面量（`--count 3` 就是 int，别加引号）
axi run jina/jina_search --query "python async" --count 3

# 复杂嵌套参数时：整体 JSON
axi run jina/jina_search --json '{"query":"python async","count":3}'
```

返回统一信封：

```json
{"status":"success","data": ...}
{"status":"error","error":"..."}
```

**`status` 字段决定分支**，不要靠退出码判断业务错误。

## 易踩坑

| 坑 | 正确做法 |
|---|---|
| `axi daemon start`（手动启动） | **不要。** MCP 工具首次调用自动拉起 daemon，空闲 30 分钟自动回收 |
| MCP 工具没有 `output_example` | 批量处理前先 `axi run` 探一次真实返回结构，再写后续代码 |
| 工具完整名搞错 | 直接用 `axi search` 返回的 `name` 字段作为完整名，不要自己拼接；所有工具（含原生）都有 `server/tool` 形式 |
| MCP server 名和 npm 包名混淆 | 以 `axi.json` 里 `mcpServers` 的 **key** 为准（例如 key 是 `jina`，不是 `jina-mcp-tools`） |

## 何时切 Python

**单次调用走 CLI；需要循环 / 聚合 / 跨调用后处理时走 Python。** 别在 Python 里 `subprocess` 调 CLI（冷启进程 + 反复 JSON 序列化，既慢又费 token）——直接 import：

```python
from axi import tool

search = tool("jina/jina_search")   # 返回可调用句柄，参数跟 `axi run --key value` 相同
results = search(query="python best practices", count=3)
```

## 命令速查

| 命令 | 用途 | 典型例子 |
|---|---|---|
| `axi search <q> [--top-k N]` | 按语义 / 意图找工具 | `axi search "订单" -k 5` |
| `axi grep <regex> [--limit N]` | 按工具名 / 描述字面模式找工具 | `axi grep "retrieval"` |
| `axi list [server]` | 枚举工具 | `axi list jina` |
| `axi describe <tool>` | 查 input_schema | `axi describe jina/jina_search` |
| `axi run <tool> --k v` 或 `--json '…'` | 执行 | `axi run jina/jina_search --query hi` |
| `axi daemon status` | 看 daemon 是否在跑 | 调试 MCP 卡顿时用 |
| `axi --help` / `axi <cmd> --help` | 查任何命令的完整参数 | 拿不准选项时首选 |

> **下游项目**：如果你的仓库基于 axi 构建且有业务契约（时区、字段语义、输出结构约定等），在自己仓库再写一份项目级 SKILL.md 补这些——本 skill 只覆盖 axi 自身的调用接口。
