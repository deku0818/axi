# axi — Agent eXecution Interface

AI Agent 与外部系统之间的统一工具层。通过 CLI 作为万能适配器，让任何工具（MCP server、Python 函数）变成 Agent 可发现、可搜索、可编程调用的命令。

## 项目状态

早期开发阶段。核心功能已实现：原生工具注册、MCP 对接、daemon 模式。

## 技术栈

- Python 3.12+
- 包管理：uv (pyproject.toml)
- CLI：Typer / 数据模型：Pydantic / MCP：mcp 官方 SDK
- 搜索：bm25s + jieba（BM25） / langchain-openai + langchain-community（Embedding）

## 设计文档

详细设计信息见 `docs/` 目录：

- [docs/design.md](docs/design.md) — 定位、设计原则、核心功能、执行模式
- [docs/architecture.md](docs/architecture.md) — 分层架构、daemon 模式、核心模块职责
- [docs/usage.md](docs/usage.md) — 使用方式定义（以终为始）
- [docs/guide.md](docs/guide.md) — 完整使用指南（面向用户和 Agent）
- [docs/tech-stack.md](docs/tech-stack.md) — 技术选型、目录结构、模块职责
- [docs/configuration.md](docs/configuration.md) — axi.json 与环境变量配置参考
- [docs/open-questions.md](docs/open-questions.md) — 待决策事项

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

### 依赖管理

- 使用 `uv add <package>` 添加依赖，**不要直接修改 pyproject.toml**
- 核心依赖：typer, pydantic, mcp, bm25s, jieba, langchain-openai, langchain-community
- 添加新依赖前需确认必要性，保持轻量

## 开发约定

- 与用户沟通使用中文
- 边开发边讨论，沟通结果及时更新到 docs/ 文档
