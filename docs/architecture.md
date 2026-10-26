# axi 架构

## 分层总览

```text
CLI / Python PTC / MCP 导出
             │
        Executor.run
         ┌───┴─────────────┐
         │                 │
     原生 Python        daemon client
      进程内执行          Unix socket
                           │
                       axi daemon
                     Registry + MCPProvider
                           │
                     MCP server 长连接
```

## 核心模块

### Daemon（后台守护进程）

维持所有 MCP server 的长连接，通过 Unix socket（`~/.axi/daemons/<hash>.sock`）接受 CLI 请求。

职责：
- 管理 MCP server 连接生命周期
- 托管 MCP 工具的 Registry
- 路由 search / describe / call_tool 请求到对应 MCP server
- 支持需要长连接的 MCP server（如 browser MCP）

文件：
- `daemon/server.py`：daemon 主进程
- `daemon/client.py`：CLI 侧客户端
- `daemon/protocol.py`：JSON 行通信协议

#### 自动启动

CLI 执行 `search`、`describe`、`run` 等命令时，`client.py` 的 `ensure_daemon()` 会：
1. 检查当前配置对应的 PID 和 socket，已就绪则复用
2. 未就绪时获取配置专属的启动文件锁，锁内复查；PID 仍存活则继续等待现有初始化进程，否则通过 `python -m axi.daemon.server` 后台启动
3. 每 0.1 秒轮询就绪状态，最多等待 60 秒；进程提前退出时立即失败

#### 启动流程

`DaemonServer.start()` 依次执行：
1. 加载 `axi.json` 配置，初始化 MCPProvider 和 Registry；按需创建 Embedding provider 和模型隔离缓存
2. 注册 SIGTERM / SIGINT 处理，确保初始化阶段也能停止
3. 创建 `~/.axi/daemons/`，清理当前配置的旧 socket，再写入 `<hash>.pid`
4. 连接 MCP server；每条连接由固定后台任务持有上下文，分页获取全部工具并注册到 Registry；单个 server 失败时关闭其连接并继续
5. 启动 Unix socket server（`~/.axi/daemons/<hash>.sock`），请求/响应读取上限均为 8 MiB
6. 启动 idle watchdog 任务

MCP 请求可以在不同请求任务中执行；重连和关闭通过连接的持有任务完成，避免跨任务退出 AnyIO 上下文。并发故障请求共用一次重连，关闭期间的失败请求不会重新拉起连接。

#### Idle Watchdog

daemon 内置空闲检测机制，防止无限占用资源：

- 每 **60 秒**检查一次空闲时间
- 每次处理请求时更新 `_last_activity` 时间戳（`status` 和 `shutdown` 请求除外，不重置计时器）
- 空闲超过 `idleTimeoutMinutes`（默认 30 分钟）后自动执行 `stop()`

#### 关闭流程

三种关闭方式，均执行相同的清理逻辑：

| 触发方式 | 说明 |
|----------|------|
| `axi daemon stop` | CLI 发送 `shutdown` 请求，daemon 优雅退出 |
| idle 超时 | watchdog 检测到空闲超时，自动关闭 |
| SIGTERM / SIGINT | 操作系统信号触发优雅关闭 |

清理步骤：关闭 socket listener → 取消 watchdog → 等各 MCP 连接的持有任务完成关闭 → 删除当前配置的 socket/PID → 注销信号处理。

CLI 的 `stop` 等待目标 PID 完成清理后才报告成功，上限 60 秒；PID 被并发启动的新实例替换时不会转而等待新实例。

#### 通信协议

CLI 和 daemon 通过 Unix socket 以 JSON Line 格式通信（每行一个完整 JSON 对象）：

- **请求**（`DaemonRequest`）：`method` + 可选参数（`tool_name`、`params`、`query`、`top_k`）
- **响应**（`DaemonResponse`）：`status`（"success" / "error"）+ `data` / `error`
- 客户端请求超时：默认 120 秒，可通过配置或 `AXI_REQUEST_TIMEOUT` 调整

### Registry（工具注册中心）

所有工具的索引，存储工具元数据（name, description, input_schema, provider 来源等），支持搜索。

职责：
- 维护工具元数据
- 提供搜索接口（默认 BM25 关键词搜索，可选 Embedding 语义搜索，支持正则匹配）
- 渐进式披露：search 返回摘要，describe 返回完整 schema

Registry 按运行位置分工：
- `runtime.py` 持有 CLI / Python PTC 共用的原生工具 Registry 和 Executor
- daemon 持有 MCP 工具 Registry
- MCP 导出持有所选工具的合并 Registry，执行前检查导出范围

### Executor（统一执行入口）

CLI、Python PTC 和 MCP 导出统一调用 `Executor.run()`：
- 解析本地工具名称，原生工具按 Pydantic 模型校验后在进程内执行
- MCP 工具通过 `daemon_request()` 调用，统一转成 RunResult
- 未在本地找到的名称交给 daemon 解析；名称歧义直接返回错误

入口只处理自己的协议：CLI 解析参数和输出 JSON，PTC 解包结果，MCP 导出检查工具范围、注入请求变量并转换 MCP 响应。三者不再分别维护执行分发逻辑。

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
├── search              # 搜索工具（BM25 / Embedding 混合 / 正则）
├── describe            # 查看工具完整 schema
├── run                 # 执行工具
└── daemon
    ├── start           # 启动 daemon
    ├── stop            # 停止 daemon
    └── status          # 查看 daemon 状态
```

## 执行流程

```text
CLI 参数解析 / PTC 调用 / MCP 请求
                 │
           Executor.run(name, params)
                 │
        ┌────────┴─────────┐
        │                  │
  原生参数校验与执行    daemon_request
        │                  │
        │             MCPProvider.call_tool
        └────────┬─────────┘
              RunResult
```
