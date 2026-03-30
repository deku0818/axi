# Changelog

## [0.0.2] - 2026-03-30

### Changed
- 原生工具 schema 提取改用 Pydantic `create_model`，支持 Literal、Optional、list[T]、嵌套 BaseModel、Annotated[..., Field()] 等高级类型
- 版本号从 0.1.0 调整为 0.0.2，反映项目早期阶段
- 代码格式化统一（ruff format）

## [0.1.0] - 2026-03-29

### Added
- 初始版本：原生工具注册、MCP 对接、daemon 模式
