---
name: axi-use
description: 通过 axi CLI 或 Python PTC 发现并调用已接入的外部工具，包括 MCP 工具和原生 Python 工具。用于用户要求查找或调用 axi 工具，或任务需要使用环境中已配置的 axi 能力；批量调用、工具组合和本地聚合使用 Python。新增工具封装、注册或 MCP 服务配置属于 axi-creator。
---

# axi 工具使用

通过按需发现获取工具信息，用 CLI 完成单次调用，用 Python 组合多次调用。保留中间数据在程序中，只把任务需要的结果带回模型上下文。

## 确定调用环境

- 配置默认是 `~/.axi/axi.json`；项目配置用 `AXI_CONFIG=/absolute/path/to/axi.json` 指定，当前目录的 `axi.json` 不会自动加载。沿用任务已有配置。
- CLI 与 Python 使用同一份 `AXI_CONFIG`。Python 解释器还需能 `import axi`；项目用 `uv add axi-cli` 安装，临时脚本可用 `uv run --with axi-cli python script.py`。仅用 `uv tool install axi-cli` 安装 CLI 不会把包安装进项目 Python 环境。
- 工具来源包括 `mcpServers`、`nativeTools` 和当前 Python 环境中已安装包的 `axi.native_tools` entry points；未发现工具时先检查环境和配置。

## 按需发现与查看

| 已知线索 | 命令 |
|---|---|
| 所需能力或意图 | `axi search "按区域查询订单" -k 3` |
| 工具名、工具组名或描述片段 | `axi grep '^orders/' -l 5` |
| 需要浏览某组工具 | `axi list orders` |
| 已知工具，需要参数或输出示例 | `axi describe orders/query_orders` |

先搜索摘要，只 describe 与任务相关的候选；已知工具及契约时直接调用，无需重复发现或枚举全库。多个候选可以一次查看：

```bash
axi describe orders/query_orders,inventory/get_stock
```

使用发现结果中的 `name` 原样调用，通常是 `server/tool`。短名仅在无歧义时可用。检查 `input_schema` 的 required、类型、枚举和约束；按需选用可选参数，不凭名称猜测接口。

`search` 默认 BM25，配置 embedding 后相关索引可增加语义检索；不能假定所有环境都启用了 embedding。当前 CLI 原生与 MCP 索引分别检索后合并，原生结果在前，`-k / -l` 是各端限制，合并数量可能更大。`grep` 按匹配顺序返回，没有相关性排序。

## 单次调用：CLI

以下示例假设已经发现 `orders/query_orders`，其 schema 包含 `region` 和 `limit`：

```bash
axi run orders/query_orders --region cn --limit 5

# 完整 JSON 对象，适合嵌套结构或需要明确类型的参数
axi run orders/query_orders -j '{"region":"cn","limit":5}'
```

`--key value` 按目标 schema 解析：字符串字段保持原文，其他字段尝试 JSON 解析。shell 引号用于传递完整参数，不决定 JSON 类型；布尔值建议显式写 `--enabled true`。

`axi run` 返回结果信封：

```json
{"status":"success","data":{"orders":[],"total":0}}
```

```json
{"status":"error","error":"Invalid params: ..."}
```

读取 JSON 的 `status` 判断执行结果；工具失败不一定产生非零退出码。搜索返回摘要数组，describe 返回元数据，发现命令的错误也可能是 `{"error":"..."}`。不要将所有输出都当成 run 信封。

## 批量与组合调用：Python PTC

循环、跨工具传参、过滤或聚合使用 Python API，避免在脚本中反复启动 CLI：

```python
from axi import tool

query_orders = tool("orders/query_orders")
result = query_orders(region="cn", limit=5)
# result 是工具数据本身，不是 {status, data} 信封
```

成功直接返回数据，失败抛出 `RuntimeError`。首次调用加载原生工具模块；原生函数在当前进程执行，MCP 调用经 daemon 保持连接。返回值可能是 dict、list、字符串或其他类型，以工具契约为准。

编写批量、并发或多工具脚本前，读取 [PTC 参考](references/ptc.md)，其中包含输出契约、有限并发、async 环境调用和错误处理。调用句柄是同步函数，不会自动并行执行。

## MCP 元工具入口

任务环境若已经通过 `axi mcp` 提供 `search / grep / describe / run`，直接使用这四个 MCP 工具完成相同流程，无需改接 CLI：

- `search(query, top_k)` 或 `grep(pattern, limit)` 获取摘要。
- `describe(name)` 查看 schema，name 支持逗号分隔。
- `run(name, params)` 执行，读取返回的 `status/data/error` 信封。

MCP 平铺模式则逐个暴露实际工具，调用其自身 schema。Python PTC 需要本地可用的 axi 配置和运行环境；仅有远端四个 MCP 元工具并不自动提供本地 `import axi` 能力。

## 排障

- MCP 连接按需自动启动，通常无需先运行 `axi daemon start`。`axi daemon status` 显示 `starting` 时表示正在连接 server，避免重复拉起进程。
- 工具缺失或连接异常时用 `axi doctor` 检查配置路径、工具来源和 MCP 状态；它可能启动 daemon 以验证连接，不会逐个试调业务工具。配置了 embedding 也不等于已验证远端 embedding 请求成功。
- 修改 MCP 配置后，运行 `axi daemon stop` 使下次调用重新加载；已有 `axi mcp` 进程也需重启。不要为普通调用重启共享的有状态连接。
- daemon 请求超时用 `AXI_REQUEST_TIMEOUT` 或 `daemon.requestTimeout` 调整；超时不代表上游操作未发生，不要盲目重试有副作用的调用。
- 参数不确定时查看 `axi <command> --help`。工具不存在时报告缺少的能力；只有任务要求接入新工具时才修改注册或配置。
