# axi 架构

## 分层总览

```
┌──────────────────────────────────────────────┐
│              AI Agent (bash)                  │
├──────────────────────────────────────────────┤
│                axi CLI                        │
│  search / describe / run / daemon             │
├──────────┬───────────────────────────────────┤
│ 原生工具 │         Unix socket               │
│ Executor │            ↓                       │
│ (进程内) │      axi daemon                    │
│          │  ┌─────────┐ ┌─────────────────┐  │
│          │  │Registry │ │ MCP Provider    │  │
│          │  │ (索引)  │ │ (连接管理)      │  │
│          │  └─────────┘ └─────────────────┘  │
├──────────┴───────────────────────────────────┤
│              工具来源（Provider）              │
│  ┌────────────┐ ┌──────────┐ ┌────────────┐ │
│  │ MCP Server │ │ Python   │ │ 未来:      │ │
│  │ (stdio 长  │ │ 装饰器   │ │ OpenAPI 等 │ │
│  │  连接)     │ │ (进程内) │ │            │ │
│  └────────────┘ └──────────┘ └────────────┘ │
└──────────────────────────────────────────────┘
```

## 核心模块

### Daemon（后台守护进程）

维持所有 MCP server 的长连接，通过 Unix socket（`~/.axi/daemon.sock`）接受 CLI 请求。

职责：
- 管理 MCP server 连接生命周期
- 托管 MCP 工具的 Registry
- 路由 search / describe / call_tool 请求到对应 MCP server
- 支持需要长连接的 MCP server（如 browser MCP）

文件：
- `daemon/server.py`：daemon 主进程
- `daemon/client.py`：CLI 侧客户端
- `daemon/protocol.py`：JSON 行通信协议

### Registry（工具注册中心）

所有工具的索引，存储工具元数据（name, description, input_schema, provider 来源等），支持搜索。

职责：
- 维护工具元数据
- 提供搜索接口（子串匹配、正则，未来可扩展 BM25、embedding）
- 渐进式披露：search 返回摘要，describe 返回完整 schema

存在两个 Registry 实例：
- CLI 进程内的 Registry：管理原生 Python 工具
- daemon 进程内的 Registry：管理 MCP 工具

### Executor（原生工具执行层）

执行原生 Python 工具，包装结构化输出。

职责：
- 调用 `@tool` 注册的 Python 函数
- 结构化输出包装（JSON 信封）
- 错误处理与状态报告

注：MCP 工具不经过 Executor，由 daemon 内的 MCPProvider 直接执行。

### Provider（工具来源适配器）

不同工具来源的适配器，将外部工具转换为 axi 内部统一表示。

已实现的 Provider：
- **MCP Provider**（`providers/mcp.py`）：连接 MCP server，读取 tool definition，管理连接池
- **Native Provider**（`providers/native.py`）：`@tool` 装饰器注册的原生 Python 函数

未来可扩展：
- OpenAPI Provider：从 OpenAPI spec 自动生成工具
- 其他

## 命令结构

```
axi
├── search              # 搜索工具（子串 / 正则）
├── describe            # 查看工具完整 schema
├── run                 # 执行工具
└── daemon
    ├── start           # 启动 daemon
    ├── stop            # 停止 daemon
    └── status          # 查看 daemon 状态
```

## 执行流程

```
axi run server/tool_name --key value
        │
        ├─ 原生工具？ → Executor 直接执行 → RunResult
        │
        └─ MCP 工具？ → daemon client → Unix socket → daemon server
                                                        │
                                                        └─ MCPProvider.call_tool()
                                                           → MCP server (stdio)
                                                           → DaemonResponse → RunResult
```
