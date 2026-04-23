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

## 通过 Python entry_points 自动发现原生工具

除了在 `axi.json` 里显式列 `nativeTools`，扩展包还可以通过 Python 的 entry_points 机制声明自己，被 pip 安装后 axi 自动发现——CWD 不需要 `axi.json` 也能用。

### 声明方式

在扩展包自己的 `pyproject.toml` 里：

```toml
[project.entry-points."axi.native_tools"]
smartlink = "smartlink_axi.tools"
```

- **group 名必须是 `axi.native_tools`**（axi 只扫这一个 group）
- entry point 的 `name` = server 名（等价于 `nativeTools[].name`）
- entry point 的 `value` = 可 import 的模块路径（`pkg.mod`；`pkg.mod:func` 形式的冒号后缀会被忽略）
- 不推荐使用 `.py` 文件路径——entry_points 的定位是"已安装的 Python 模块"，请写成 `pkg.mod` 这种形式

装完即生效：

```bash
pip install smartlink-axi
axi list     # 自动列出 smartlink 的工具，CWD 无需 axi.json
```

### 与 `axi.json` 的合并规则

- **取并集**：`axi.json.nativeTools` + 所有已安装包声明的 entry_points 全部加载
- **按模块路径去重**：同一个模块被两边声明时只加载一次
- **同模块冲突时 `axi.json` 赢**：遍历顺序先 `axi.json` 再 entry_points；前者先占住模块路径，后者的同模块声明被跳过
- **不同模块声明同一个 server 名**：允许；axi 会输出 warning 但继续加载，两边工具都挂到该 server 下
- **模块加载失败**：不占位、不中断其它模块；错误写到日志里，用户侧看到的就是"这个 server 不见了"

### 哪些字段能通过 entry_points 贡献？

**只有原生工具模块**（`nativeTools` 这一维）。`cli / mcpServers / search / daemon` 仍然只能由 `axi.json` 提供——扩展包不应该替部署者决定 embedding provider、MCP 连接、CLI 偏好等基础设施配置。

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
