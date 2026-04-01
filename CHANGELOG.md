# Changelog

## [0.0.3] - 2026-04-01

### Added
- BM25 关键词搜索（bm25s + jieba 分词，支持中英文）
- Embedding 语义搜索（Jina/OpenAI，通过 LangChain 接入，可选）
- 混合搜索（BM25 + Embedding，RRF 融合排序，分数归一化 0-1）
- `axi grep` 命令：独立的正则表达式搜索
- `axi daemon status` 输出 JSON 格式状态信息（PID、运行时长、工具统计）
- Daemon idle 超时自动关闭机制
- `config.py` 统一配置模块（`axi.json` 解析 + Pydantic 模型）
- `docs/configuration.md` 配置参考文档
- Embedding 文件缓存（`.axi/` 目录）
- MCP 工具调用失败时自动重连一次

### Changed
- `axi search` 从子串匹配改为 BM25 混合搜索
- 搜索结果新增 `score` 字段
- `ToolResolveError` 拆分为 `ToolNotFoundError` 和 `AmbiguousToolError`
- Daemon 启动不再需要 `--config` 参数，统一从 `axi.json` 读取
- MCP/原生工具配置统一通过 `config.py` 管理，移除分散的配置解析逻辑

## [0.0.2] - 2026-03-30

### Changed
- 原生工具 schema 提取改用 Pydantic `create_model`，支持 Literal、Optional、list[T]、嵌套 BaseModel、Annotated[..., Field()] 等高级类型
- 版本号从 0.1.0 调整为 0.0.2，反映项目早期阶段
- 代码格式化统一（ruff format）

## [0.1.0] - 2026-03-29

### Added
- 初始版本：原生工具注册、MCP 对接、daemon 模式
