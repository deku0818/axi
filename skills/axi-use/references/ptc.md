# Python PTC：批量、组合与并发

## 先确认契约

使用 `axi describe <tool>` 检查输入 schema 和可选 `output_example`。当前 axi 的工具元数据未保留上游 MCP 的输出 schema；返回结构以工具文档、输出示例和实际数据为准。

缺少输出示例时，先读已有接口文档；对只读工具可用最小参数调用一次确认返回结构。有副作用的工具不要为探测结构额外执行一次。

Python API 的行为：

```python
from axi import tool

query = tool("orders/query_orders")
data = query(region="cn", limit=5)  # 仅接受关键字参数
```

- `tool("name")` 创建同步调用句柄，实际调用时才发现原生工具并执行。
- 成功直接返回工具数据；`data["status"]` 只有在业务数据本身定义该字段时才有意义。
- 执行错误抛 `RuntimeError`。配置加载等初始化失败也可能抛其他异常或终止进程，应先确认配置和依赖。
- 保留真实结构，不把所有 MCP 返回值都当 dict；文本结果需要按实际格式解析。
- CLI 和脚本使用相同的 `AXI_CONFIG`，在启动解释器前设置。配置在 import 时加载，不要在同一解释器中靠修改环境变量切换工具集。

## 批量查询，在本地聚合

以下示例假设已经确认 `orders/query_orders` 接受 `region / limit`，返回 `{"orders":[{"amount":120}],"total":1}`。它只汇总返回的当前页；若任务要求全部记录，按工具真实的分页契约继续取数。

```python
import json
from axi import tool

query = tool("orders/query_orders")
totals = []

for region in ["cn", "jp", "us"]:
    data = query(region=region, limit=100)
    totals.append({
        "region": region,
        "returned": len(data["orders"]),
        "total": data["total"],
        "amount": sum(order["amount"] for order in data["orders"]),
    })

print(json.dumps(totals, ensure_ascii=False))
```

通过 `uv run --with axi-cli python script.py` 或已经安装 axi 的项目解释器执行。只输出需要的字段、统计和错误摘要，中间原始数据留在程序中。

组合多个工具时，分别用 `tool("server/name")` 获取句柄，将上一步返回值中的真实字段作为下一步的关键字参数。存在数据依赖的步骤按顺序执行；不要猜测尚未 describe 的第二个工具的参数。

## 有限并发与逐项错误

独立且允许并发的调用可以使用线程池。根据上游限流和状态要求设置 `max_workers`；有状态会话、依赖顺序的写入等仍按顺序执行。

```python
import json
from concurrent.futures import ThreadPoolExecutor

from axi import tool

query = tool("orders/query_orders")


def summarize(region: str) -> dict:
    try:
        data = query(region=region, limit=100)
        return {
            "region": region,
            "amount": sum(order["amount"] for order in data["orders"]),
        }
    except RuntimeError as exc:
        return {"region": region, "error": str(exc)}


with ThreadPoolExecutor(max_workers=3) as pool:
    results = list(pool.map(summarize, ["cn", "jp", "us"]))

print(json.dumps(results, ensure_ascii=False))
```

这里选择逐项收集调用错误；若任务要求全部成功再继续，让异常中断流程即可。汇总时区分失败项和空结果，不将失败计为零。不自动重试可能已执行的写操作。

## 在 async 程序中调用

PTC 内部可能运行自己的事件循环，不能在已有事件循环的线程中直接调用，也不能直接 `await query(...)`。用 `asyncio.to_thread` 转交同步接口，并按需用 semaphore 限制批量并发：

```python
import asyncio

from axi import tool

query = tool("orders/query_orders")


async def main() -> None:
    data = await asyncio.to_thread(query, region="cn", limit=5)
    print(data)


asyncio.run(main())
```

在已有的 async 函数中只使用 `await asyncio.to_thread(...)` 部分。取消等待不保证后台线程或上游请求被取消；超时后先确认实际状态再决定是否重试。
