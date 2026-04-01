# 技术选型

## 依赖

| 模块 | 选择 | 理由 |
|------|------|------|
| CLI 框架 | **Typer** | 类型提示驱动，JSON 输出友好，Pydantic 集成 |
| 数据模型 | **Pydantic** | 输入输出校验，schema 自动生成 |
| 搜索 | **BM25**（bm25s + jieba）+ **Embedding**（Jina/OpenAI，LangChain） | BM25 默认启用，Embedding 可选，RRF 混合排序 |
| MCP 客户端 | **mcp** | Anthropic 官方 SDK，标准 stdio/SSE 传输 |
| 构建后端 | **hatchling** | 现代，与 uv 配合好 |

### 选型取舍

- **搜索**：默认 BM25（bm25s + jieba 分词，支持中英文），可选启用 Embedding 语义搜索（Jina/OpenAI，通过 LangChain 接入），两者通过 RRF 混合排序。正则匹配仍可用。
- **mcp 官方 vs FastMCP**：先用官方轻量 SDK，够用。FastMCP 功能更丰富但更重，后续需要再切。
- **Typer vs Click**：Typer 基于 Click 但更 Pythonic，类型提示自动生成参数，适合 JSON-first 的设计理念。
- **daemon IPC**：Unix domain socket + JSON 行协议，轻量、无额外依赖，macOS/Linux 原生支持。

## 目录结构

```
axi/
├── docs/                       # 设计文档
│   ├── design.md               # 定位、设计原则、核心功能
│   ├── architecture.md         # 分层架构、核心模块职责
│   ├── usage.md                # 使用方式定义（以终为始）
│   ├── tech-stack.md           # 技术选型与目录结构（本文件）
│   └── open-questions.md       # 待决策事项
├── src/
│   └── axi/
│       ├── __init__.py         # 公开 API: tool 装饰器, tool() 函数
│       ├── cli.py              # Typer 入口: search / describe / run / daemon
│       ├── registry.py         # 工具注册中心 + 搜索
│       ├── executor.py         # 原生工具执行层
│       ├── models.py           # Pydantic 数据模型（ToolMeta, RunResult 等）
│       ├── daemon/
│       │   ├── __init__.py
│       │   ├── server.py       # daemon 主进程：维持 MCP 连接，监听 Unix socket
│       │   ├── client.py       # CLI 侧 daemon 客户端
│       │   └── protocol.py     # 请求/响应协议定义
│       ├── providers/
│       │   ├── __init__.py
│       │   ├── mcp.py          # MCP provider: 读 axi.json, 管理连接
│       │   └── native.py       # 原生 provider: @tool 装饰器注册
│       └── search/
│           ├── __init__.py
│           ├── bm25.py         # BM25 搜索实现（bm25s + jieba 分词）
│           ├── embedding.py    # Embedding 语义搜索实现（LangChain）
│           ├── hybrid.py       # 混合搜索（RRF 融合排序）
│           └── regex.py        # 正则匹配实现
├── tests/
├── axi.json                    # axi 配置：mcpServers + nativeTools（用户编辑）
├── pyproject.toml
├── CLAUDE.md
└── README.md
```

### 模块职责

- **`__init__.py`**：对外暴露 `@tool` 装饰器和 `tool()` 函数，是 PTC 和原生注册的入口
- **`cli.py`**：Typer app，定义 `axi search`、`axi describe`、`axi run`、`axi daemon` 子命令
- **`registry.py`**：工具注册中心，维护元数据索引，提供搜索接口
- **`executor.py`**：原生工具执行层，包装结构化输出
- **`models.py`**：Pydantic 模型，定义 ToolMeta、RunResult 等核心数据结构
- **`daemon/server.py`**：daemon 主进程，维持 MCP 连接，监听 Unix socket 处理请求
- **`daemon/client.py`**：CLI 侧客户端，向 daemon 发送请求并接收响应
- **`daemon/protocol.py`**：定义 DaemonRequest / DaemonResponse，Unix socket 路径等常量
- **`providers/mcp.py`**：读取 `axi.json`，管理 MCP server 连接和工具调用
- **`providers/native.py`**：`@tool` 装饰器实现，从函数签名提取 schema 并注册；加载 `nativeTools` 配置（对象格式 `{"module": "...", "name": "..."}`，name 可选，自动推导）
- **`search/bm25.py`**：BM25 关键词搜索实现，基于 bm25s + jieba 分词
- **`search/embedding.py`**：Embedding 语义搜索实现，通过 LangChain 接入 Jina/OpenAI
- **`search/hybrid.py`**：混合搜索，通过 RRF（Reciprocal Rank Fusion）融合 BM25 和 Embedding 结果，分数归一化到 0-1
- **`search/regex.py`**：正则匹配实现
