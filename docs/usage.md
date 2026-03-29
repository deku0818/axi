# axi 使用方式

以终为始，从使用者视角定义 axi 的交互方式。

## 场景一：Agent 通过 bash 使用

```bash
# 查看所有 server 和工具
axi list

# 查看指定 server 的工具详情
axi list jina-mcp-tools

# 搜索工具（BM25）
axi search "网页抓取"

# 搜索工具（正则）
axi search --regex "read_.*"

# 查看工具详情（input_schema、description，原生工具可能包含 output_example）
axi describe jina-mcp-tools/read_url

# 执行工具
axi run jina-mcp-tools/read_url --url "https://example.com"
```

## 场景二：Agent 通过 PTC 批量调用

```python
from axi import tool

read_url = tool("jina-mcp-tools/read_url")
search = tool("jina-mcp-tools/search")

# 批量调用，本地聚合
urls = ["https://a.com", "https://b.com", "https://c.com"]
results = [read_url(url=u) for u in urls]
summary = [r["title"] for r in results if r["status"] == "success"]
```

### PTC 与 output 格式

PTC 场景下 Agent 需要知道返回数据结构才能写处理代码：

- **原生注册的工具**：开发者可通过 `output_example` 声明返回格式，`axi describe` 可展示
- **MCP 来源的工具**：MCP 协议不包含 output_schema，Agent 需先 `axi run` 试调一次查看真实返回结构，再编写批量处理代码

## 场景三：开发者注册原生工具

```python
from axi import tool

@tool(
    name="query_orders",
    description="按区域查询订单",
    output_example={"orders": [{"id": 1, "region": "cn", "amount": 100}], "total": 1}
)
def query_orders(region: str, limit: int = 10) -> dict:
    return db.execute(...)
```

注册后自动可通过 `axi run tools/query_orders --region cn` 和 PTC 两种方式使用（`tools` 是该模块的 server 名）。

## 场景四：配置 MCP server

编辑 `axi.json` 即可，无需额外命令：

```json
{
    "mcpServers": {
        "jina-mcp-tools": {
            "command": "npx",
            "args": ["jina-mcp-tools"],
            "env": {
                "JINA_API_KEY": "xxx"
            }
        }
    },
    "nativeTools": [
        {"module": "my_project.tools"},
        {"module": "./scripts/tools.py", "name": "scripts"}
    ]
}
```

`nativeTools` 只支持对象格式：

- **module**（必填）：Python 模块路径（如 `"my_project.tools"`）或文件路径（如 `"./scripts/tools.py"`）
- **name**（可选）：作为 server 名。省略时自动推导——文件路径取 stem，模块路径取最后一段

axi 启动时自动读取配置，发现所有 MCP 工具和原生工具。MCP server 的 key 名作为 server 名称，原生工具的 name 作为 server 名称，调用格式统一为 `server/tool_name`。

## 输出约定

所有命令输出统一为紧凑 JSON。
