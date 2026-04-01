# 待决策事项

## 已决策

### 1. 工具元数据持久化

**已决定**：MCP 工具元数据不单独持久化。daemon 维持长连接，启动时从 MCP server 实时获取 tool list。原生工具通过 `@tool` 装饰器在代码加载时注册。

### 2. MCP 连接生命周期

**已决定**：采用 daemon 模式。daemon 后台常驻，维持所有 MCP server 的 stdio 长连接。CLI 通过 Unix socket 与 daemon 通信。支持需要长连接的 MCP server（如 browser MCP）。

### 3. PTC 执行环境

**已决定**：Agent 直接 `python script.py` + `import axi`。`tool("name")` 返回可调用对象，底层通过 daemon 执行 MCP 工具。

### 4. 工具命名空间

**已决定**：MCP server 的 config key 名（如 `jina-mcp-tools`、`github`）天然作为 server 名，调用格式为 `server/tool_name`。原生工具无 server 前缀。

### 5. 搜索策略

**已决定**：默认使用 BM25 关键词搜索（bm25s + jieba 分词），支持中英文。可选启用 Embedding 语义搜索（Jina/OpenAI，通过 LangChain 接入），两者通过 RRF（Reciprocal Rank Fusion）混合排序，分数归一化到 0-1。正则匹配通过独立的 `axi grep` 命令提供。搜索配置通过 `axi.json` 的 `search.embedding` 字段管理。

## 待决策

### 6. 权限模型

是否加入安全与权限控制？

选项：
- **暂不做**：先跑通核心流程
- **工具粒度**：某个工具需要授权才能调用
- **参数粒度**：如 `rm` 只允许特定路径

### 7. daemon 配置热更新

修改 `axi.json` 后是否需要重启 daemon？

选项：
- **需要重启**：当前行为，`axi daemon stop && axi daemon start`
- **热更新**：daemon 监听配置文件变化，自动重新连接
- **手动 reload**：`axi daemon reload` 命令

### 8. daemon 空闲自动退出

daemon 启动后常驻后台，是否需要空闲超时自动关闭？

选项：
- **不做**：当前行为，一直运行直到手动 stop 或系统重启
- **空闲超时**：N 分钟无请求后自动退出，下次使用时自动拉起

### 9. 多项目隔离

不同项目目录可能有不同的 `axi.json`。daemon 是全局唯一还是按项目隔离？

选项：
- **全局唯一**：当前行为，所有项目共享一个 daemon
- **按项目隔离**：每个项目目录一个 daemon 实例
