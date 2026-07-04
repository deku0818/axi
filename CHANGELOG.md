# Changelog

## [0.0.6] - 2026-07-03

### Added
- `axi mcp` 命令：将 axi 工具导出为 MCP server，实现"写一次，CLI + MCP 两用"
  - `--transport stdio|http`：stdio（默认，由 MCP 客户端拉起）或 streamable HTTP（`--port`/`--host`）
  - `--server a,b`：只暴露指定 server 的工具（逗号分隔多个）
  - 平铺模式：每个工具注册为独立 MCP tool（单 server 用裸名，多 server 加 `server__` 前缀）；元工具模式：只暴露 `search`/`grep`/`describe`/`run` 四个工具，渐进式披露
  - 缺省形态自动判定：指定 `--server` → 平铺，全量 → 元工具；`--flat`/`--meta` 强制覆盖
- `axi daemon status` 输出新增 `config_path` 字段
- 执行前参数校验：native 工具按 Pydantic 参数模型校验并转换（字符串数字 → int、嵌套 dict → BaseModel 实例、多余字段报错）；MCP 工具由 daemon 按 `input_schema` 做 jsonschema 校验。非法参数返回 `{"status":"error","error":"Invalid params: ..."}`，不再触达工具本体

### Fixed
- MCP 工具返回 `isError` 结果时被包成 `{"status":"success"}` 的问题：现在正确落进 error 信封，且工具级错误不再触发无意义的重连重试
- `axi mcp` 长驻进程在 daemon idle 超时后 MCP 工具永久不可用：执行路径统一走 `daemon_request`（内含自动重启）
- 两个模块注册同名 native 工具时相互遮蔽（静默执行错误的函数）：函数/模型注册键改为 full_name
- `**kwargs` 签名的 `@tool` 函数在参数校验下不可调用：`*args`/`**kwargs` 不再进参数模型，有 `**kwargs` 时放行多余字段
- 参数校验与 CLI 类型猜测的冲突：native 侧启用 `coerce_numbers_to_str`（`--name 42` → "42"），daemon 侧按 schema 顶层类型做轻量转换（`--port 08080` → 8080）
- schema 含不可解析 `$ref` 时工具不可调用：校验兜底放宽为除 ValidationError 外一律放行
- 平铺模式下清洗后同名的工具静默覆盖：按注册顺序加 `_2`/`_3` 后缀
- `axi mcp --server` 把"配置了但没连上"的 MCP server 误报为"不存在"：现在区分两种情况并指向 daemon 日志
- cwd 存在 `./axi.json` 但未设 `AXI_CONFIG` 时输出迁移提示（0.0.5 → 0.0.6 升级不再静默丢工具）
- uvicorn / starlette / httpx 从传递依赖转为显式声明

### Changed
- **Breaking**：配置文件不再从当前目录读取 `./axi.json`；默认路径改为 `~/.axi/axi.json`，项目级配置通过 `AXI_CONFIG` 环境变量指定
- **Breaking**：daemon 按配置文件隔离，每份 `AXI_CONFIG` 对应独立 daemon；socket/pid/log 移至 `~/.axi/daemons/<配置路径哈希>.*`（原 `~/.axi/daemon.sock` 废弃）

## [0.0.5] - 2026-04-23

### Added
- Python entry_points 自动发现原生工具：扩展包在 `pyproject.toml` 里声明 `[project.entry-points."axi.native_tools"]` 即可被 axi 自动发现，无需 `axi.json` 登记
- `docs/configuration.md` 补充 entry_points 机制说明与合并规则（去重、同名 server collision、加载失败降级）

### Changed
- `load_native_tool_modules` 从 `providers/mcp.py` 搬到 `providers/native.py`，职责回归原生工具 Provider
- 模块加载失败时不再占位，避免对后续合法包误报 server 名 collision

## [0.0.4] - 2026-04-20

### Added
- `AXI_CONFIG` 环境变量：自定义 `axi.json` 配置文件路径
- GitHub Actions workflow：打 `v*` tag 时自动通过 trusted publishing 发布到 PyPI
- `pyproject.toml` 新增 sdist 打包排除规则（`.github/`、`docs/`、`tests/`、`uv.lock` 等）
- README 补充 daemon 自动管理、生命周期、状态输出、文件位置等完整说明
- `docs/architecture.md` 补充 daemon 启动流程、idle watchdog、关闭流程、通信协议章节

### Changed
- 包名由 `axi` 重命名为 `axi-cli`（PyPI 发布名）
- 安装方式从 `uv pip install -e .` 改为 `uv sync`

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
