# axi — Agent eXecution Interface

AI Agent 与外部系统之间的统一工具层。通过 CLI 作为万能适配器，让任何工具（MCP server、Python 函数等）变成 Agent 可发现、可搜索、可编程调用的命令。

## 代码风格

代码应当具备可读性、简洁性和高效性。

- 架构采用分层设计：底层提供基本操作和数据结构，组合后具备充分的灵活性；高层提供开箱即用的 API，足以满足大多数使用场景。
- 偏好简洁明确的函数，每个函数专注于单一任务，输入和输出类型应明确指定。
- 用最少的代码解决问题，不要任何预设之外的东西，如果你写了 200 行，而 50 行足矣，推倒重写。
- 不为不可能发生的场景写错误处理。
- 自问一句："一位资深工程师看到这段代码，会觉得过度设计吗？"答案若是肯定，就精简。

## 依赖管理

项目使用 uv 管理；项目依赖始终使用 uv 进行管理，而非直接改 `pyproject.toml`。

## 技术栈

- Python 3.12+
- 包管理：uv (pyproject.toml)
- CLI：Typer / 数据模型：Pydantic / MCP：mcp 官方 SDK
- 搜索：bm25s + jieba（BM25） / langchain-openai + langchain-community（Embedding）

## 快速参考

- **设计原则**：渐进式披露（search → describe → run）
- **工具来源**：MCP 导入（axi.json mcpServers）/ Python `@tool` 装饰器原生注册（axi.json nativeTools，对象格式 `{"module": "...", "name": "..."}`，module 支持文件路径和模块路径，name 可选自动推导）
- **MCP 执行**：通过 daemon 长连接，支持有状态 MCP server（如 browser MCP）
- **搜索策略**：BM25（bm25s + jieba 分词，默认） + Embedding（Jina/OpenAI API，可选） + 正则（`axi grep`）；混合搜索用 RRF 融合，分数归一化到 0-1
- **搜索配置**：`axi.json` 的 `search.embedding` 段，支持 `provider`（"jina"/"openai"）、`apiKey`（可选，不填从环境变量读 `JINA_API_KEY`/`OPENAI_API_KEY`）、`model`（可选）、`baseUrl`（可选）
- **输出**：统一紧凑 JSON

## 代码规范

### 项目结构

```
src/axi/
├── __init__.py         # 公开 API: @tool 装饰器, tool() 函数
├── cli.py              # Typer 入口: search / grep / describe / run / daemon
├── registry.py         # 工具注册中心 + 搜索
├── executor.py         # 原生工具执行层
├── models.py           # Pydantic 数据模型
├── daemon/
│   ├── server.py       # daemon 主进程：维持 MCP 连接，监听 Unix socket
│   ├── client.py       # CLI 侧 daemon 客户端
│   └── protocol.py     # 请求/响应协议定义
├── providers/
│   ├── mcp.py          # MCP provider: 连接管理 + 工具调用
│   └── native.py       # 原生 @tool 装饰器
└── search/
    ├── regex.py        # 正则搜索（grep 命令）
    ├── tokenize.py     # 中英文混合分词（jieba）
    ├── bm25.py         # BM25 搜索（封装 bm25s）
    ├── embedding.py    # Embedding 搜索（Jina/OpenAI API）
    ├── hybrid.py       # 混合搜索（BM25 + Embedding，RRF 融合）
    └── cache.py        # Embedding 文件缓存
```

### 编码原则

- **Pydantic 优先**：所有数据结构用 Pydantic model 定义，不用 raw dict
- **类型提示**：所有函数必须有完整的 type hints
- **JSON-first**：CLI 输出默认 JSON，通过 Pydantic 的 `.model_dump_json()` 序列化
- **统一输出信封**：所有 `axi run` 结果包装为 `{"status": "success"|"error", "data": ..., "error": ...}`
- **MCP 走 daemon**：MCP 工具一律通过 daemon 执行，不在 CLI 进程内直连
- **原生走进程内**：`@tool` 注册的原生工具在 CLI 进程内直接执行
- **搜索可插拔**：BM25 + Embedding 混合搜索为默认（`search` 命令），正则为独立的 `grep` 命令

### 命名约定

- MCP 工具：`axi.json` 的 `mcpServers` key 名作为 server 名，调用格式 `server/tool_name`
- 原生工具：`nativeTools` 的 `name` 字段作为 server 名（省略时自动推导：文件路径取 stem，模块路径取最后一段），调用格式同样为 `server/tool_name`

### Skills 编写与同步

`skills/` 下的 SKILL.md 是项目对外的 Agent 使用文档（随包分发），**质量和同步都是代码规范的一部分**。

- **同步**：提交前跑 `/sync-skills`，该命令会扫描 diff、识别对外行为改动、逐个比对 skill 并协助更新
- **Description 即触发器**：frontmatter 的 `description` 明确列"做什么 + 何时触发 + 反向 skip 条件"；表述略 pushy（Claude 倾向 undertrigger，过于保守反而用不到）
- **渐进式披露**：SKILL.md body 以"信息密度高、便于 Agent 速读"为目标，紧凑优先（参考现有两个 skill 的 ~120 行体量）；超出时拆到 `references/` 子目录按需加载，命令级参数交给 `--help`
- **祈使句 + 解释 why**：用"先 X 再 Y"而非"应该 / 可以"；说明原因而非堆 MUST；保持通用，别绑死到某个超窄示例
- **自包含**：不引用仓库内 `docs/*`（pip 分发后不可达），兜底用 `--help` 或指向源码

