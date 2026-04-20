# axi 配置参考

axi 通过项目根目录的 `axi.json` 文件和环境变量进行配置。

---

## axi.json

默认路径为项目根目录下的 `axi.json`。配置在进程启动时加载一次，全局共享。

### 完整结构

```json
{
  "cli": { ... },
  "mcpServers": { ... },
  "nativeTools": [ ... ],
  "search": { ... },
  "daemon": { ... }
}
```

所有字段均为可选，缺省时使用默认值。

---

### cli

CLI 显示配置。

```json
{
  "cli": {
    "rich": true
  }
}
```

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `rich` | boolean | `false` | 启用 Rich 格式化输出（环境变量 `AXI_RICH` 优先级更高） |

---

### mcpServers

MCP server 定义。每个 key 作为 server 命名空间，工具以 `server/tool_name` 格式调用。

每个 server 必须提供 `command`（本地进程）或 `url`（HTTP 流式传输）之一。

```json
{
  "mcpServers": {
    "jina": {
      "command": "npx",
      "args": ["jina-mcp-tools"],
      "env": { "JINA_API_KEY": "jina_xxx" }
    },
    "retrieval": {
      "url": "http://localhost:8000/mcp"
    }
  }
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `command` | string | 与 `url` 二选一 | 启动 MCP server 的命令 |
| `args` | string[] | 否 | 命令参数，默认 `[]` |
| `env` | object | 否 | 传递给子进程的环境变量 |
| `url` | string | 与 `command` 二选一 | HTTP streaming 地址 |

---

### nativeTools

Python 原生工具模块声明。通过 `@tool` 装饰器注册的函数自动成为可调用工具。

```json
{
  "nativeTools": [
    { "module": "my_project.tools" },
    { "module": "./scripts/tools.py", "name": "scripts" }
  ]
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `module` | string | 是 | Python 模块路径或文件路径 |
| `name` | string | 否 | server 名，省略时自动推导（文件取 stem，模块取末段） |

---

### search

搜索引擎配置。

#### search.embedding

启用 Embedding 语义搜索。不配置则仅使用 BM25 关键词搜索。

```json
{
  "search": {
    "embedding": {
      "provider": "jina",
      "model": "jina-embeddings-v3"
    }
  }
}
```

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `provider` | string | 是 | — | `"jina"` 或 `"openai"` |
| `apiKey` | string | 否 | 从环境变量读取 | API 密钥，省略时读 `JINA_API_KEY` / `OPENAI_API_KEY` |
| `model` | string | 否 | 取决于 provider | 模型名称 |
| `baseUrl` | string | 否 | — | 自定义 API 端点（OpenAI 兼容格式） |

#### search.weights

混合搜索 RRF 融合权重。

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `bm25` | number | `0.3` | BM25 权重 |
| `embedding` | number | `0.7` | Embedding 权重 |

---

### daemon

Daemon 进程配置。

```json
{
  "daemon": {
    "idleTimeoutMinutes": 30
  }
}
```

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `idleTimeoutMinutes` | number | `30` | 空闲自动关闭时间（分钟） |

Daemon 运行时文件位于 `~/.axi/`：
- `daemon.sock` — Unix socket，CLI 与 daemon 的通信通道
- `daemon.pid` — 进程 PID 文件，用于检测 daemon 是否存活
- `daemon.log` — daemon 启动和错误日志

---

## 环境变量

| 变量 | 说明 | 默认 |
|------|------|------|
| `AXI_CONFIG` | 自定义 `axi.json` 路径 | `axi.json`（当前工作目录） |
| `AXI_RICH` | 设为 `1`/`true` 启用、`0`/`false` 禁用 Rich 格式化（优先于 `cli.rich`） | 未设置时取 `cli.rich` |
| `JINA_API_KEY` | Jina Embedding API 密钥（`search.embedding.apiKey` 未配置时使用） | — |
| `OPENAI_API_KEY` | OpenAI Embedding API 密钥（`search.embedding.apiKey` 未配置时使用） | — |

```bash
# 自定义配置文件路径
AXI_CONFIG=/path/to/custom.json axi list

# 启用 Rich 格式化
AXI_RICH=1 axi search "web"

# 通过环境变量提供 API 密钥
export JINA_API_KEY=jina_xxx
axi search "web search"
```

---

## 最小配置示例

```json
{
  "mcpServers": {
    "jina": {
      "command": "npx",
      "args": ["jina-mcp-tools"],
      "env": { "JINA_API_KEY": "your-key" }
    }
  }
}
```

## 完整配置示例

```json
{
  "cli": {
    "rich": false
  },
  "mcpServers": {
    "jina": {
      "command": "npx",
      "args": ["jina-mcp-tools"],
      "env": { "JINA_API_KEY": "jina_xxx" }
    },
    "retrieval": {
      "url": "http://localhost:8000/mcp"
    }
  },
  "nativeTools": [
    { "module": "./tools/my_tools.py", "name": "my" }
  ],
  "search": {
    "embedding": {
      "provider": "jina",
      "model": "jina-embeddings-v3"
    },
    "weights": {
      "bm25": 0.3,
      "embedding": 0.7
    }
  },
  "daemon": {
    "idleTimeoutMinutes": 60
  }
}
```
