# MCP 接入与导出

## 导入已有 MCP server

将对应项合并进 `AXI_CONFIG` 指向的配置（默认 `~/.axi/axi.json`）。以下命令、URL 和凭据需要替换为实际服务：

```json
{
  "mcpServers": {
    "local": {
      "command": "uvx",
      "args": ["your-mcp-package"],
      "env": {"API_KEY": "your-key"}
    },
    "remote": {
      "url": "http://localhost:8000/mcp",
      "headers": {"Authorization": "Bearer your-token"}
    }
  }
}
```

本地进程使用 `command / args / env`，Streamable HTTP 使用 `url / headers`。为每个 server 选用一种传输配置；当前 provider 在存在 `url` 时优先使用 HTTP，不会将 stdio 的 env 转成 HTTP 认证头。

`mcpServers` 的 key 是工具组名，例如 `local/echo`，不取决于包名。MCP 工具经 daemon 执行，PTC 可直接用 `tool("local/echo")` 获取句柄；无需再为已有 MCP 工具写一个 Python 包装层。

MCP 配置在 daemon 启动时加载。已有 daemon 运行时，保存配置不会立即更新连接或工具集；需要停止旧 daemon，让下一次请求重新启动。若用户正在使用有状态 MCP 会话，考虑重启会中断该会话。已运行的导出进程也需要重新启动才能刷新注册表。

```bash
axi daemon stop
axi list local
axi grep '^local/'
```

首次连接自动启动 daemon，`status: starting` 表示连接中，`status: running` 表示 socket 已就绪。`axi doctor` 可核对实际配置、连接和工具来源，不会执行每个业务工具。不要将 server 连接故障直接判断成工具不存在。

## 导出：按工具规模选择模式

```bash
# 元工具：默认全量，仅暴露 search / grep / describe / run
axi mcp

# 平铺：指定组时默认逐个暴露工具
axi mcp --server orders

# 限定组范围，同时保留按需发现
axi mcp --server orders,inventory --meta

# 全量平铺（工具少且客户端需要直接看到每个工具时）
axi mcp --flat

# HTTP 元工具服务，默认监听 127.0.0.1:8321/mcp
axi mcp --transport http --port 8321
```

- 元工具模式固定注册四个入口，按需返回摘要、schema 和结果，减少预加载工具定义的上下文成本；后续发现与执行内容仍占用上下文。
- 平铺模式直接暴露每个工具的 schema；单组使用裸工具名，多组加 `server__` 前缀，清洗后的冲突名追加数字后缀。
- `--server a,b` 限定导出范围，native 和已导入的 MCP 工具都可选择；`--meta / --flat` 覆盖默认模式。
- 元工具 `run(name, params)` 返回 axi 的 `status/data/error` 信封；平铺调用成功直接返回工具数据，失败设置 MCP 的工具错误标志。客户端读取的是 MCP content 中的结果，不要将两种模式当成相同的信封。

## 客户端配置

下面使用四个元工具；客户端需能找到 `axi`，必要时将 command 换成可执行文件绝对路径：

```json
{
  "mcpServers": {
    "axi": {
      "command": "axi",
      "args": ["mcp"],
      "env": {"AXI_CONFIG": "/absolute/path/to/axi.json"}
    }
  }
}
```

单组平铺可将 args 改为 `["mcp", "--server", "orders"]`。这里的 `AXI_CONFIG` 是 axi 实际加载的工具配置；客户端配置文件与 axi 的工具配置是两份不同用途的文件。

HTTP 客户端使用 URL，可为原生工具传递请求级变量：

```json
{
  "mcpServers": {
    "axi": {
      "url": "http://localhost:8321/mcp",
      "headers": {"Axi-API-KEY": "your-key", "Axi-REGION": "cn"}
    }
  }
}
```

原生工具内通过 `axi.env` 读取，按请求隔离，优先于进程环境变量。它不自动转发为上游 MCP 凭据，也不提供服务端准入鉴权。需要让其他机器访问时可配置 `--host`，并按实际部署要求提供认证入口。

## 验证导出

先验证 CLI 的发现、schema 和授权范围内的调用；再用实际 MCP 客户端检查 tools/list：元工具模式应只有四个入口，平铺模式应包含预期工具，范围限制应符合配置。确认描述、调用参数、成功数据和错误结果均可被客户端读取。stdio 的 stdout 是协议通道，原生工具的诊断日志写 stderr，避免 print 污染协议。
