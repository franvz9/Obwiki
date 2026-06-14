# LLMWiki MCP Server

面向 AI Agent 的知识库工具层。19 个 MCP 工具，设计参考 [Nowledge Mem](https://mem.nowledge.co/zh/docs) 的 MCP 模式。

## 安装

```bash
cd mcp && uv venv && source .venv/bin/activate && uv pip install -e .
```

## Claude Code 配置

在 `~/.claude/claude_desktop_config.json` 或项目的 `.claude/mcp.json` 中添加：

```json
{
  "mcpServers": {
    "llmwiki": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/llmwiki/mcp", "mcp", "run", "src/server.py"],
      "env": {
        "LLMWIKI_API_URL": "http://localhost:8742"
      }
    }
  }
}
```

## 工具矩阵

### 知识库管理
| 工具 | 说明 | 必填参数 |
|------|------|---------|
| `kb.list` | 列出所有知识库 | — |
| `kb.status` | 获取知识库状态 | kb_id(可选) |
| `kb.activate` | 激活知识库 | kb_id |
| `kb.initialize` | 初始化目录结构 | kb_id |

### 读写操作
| 工具 | 说明 | 必填参数 |
|------|------|---------|
| `kb.search` | FTS5 全文搜索 | query |
| `kb.read` | 读取文件内容 | path |
| `kb.write` | 创建/更新 wiki 页面 | path, content |
| `kb.index` | 获取 wiki 索引/目录树 | — |
| `kb.tree` | 完整目录树 | — |

### 知识图谱
| 工具 | 说明 | 必填参数 |
|------|------|---------|
| `kb.graph` | 图谱数据 (edges/clusters/gaps) | — |
| `kb.crystals` | 结晶列表 | — |
| `kb.communities` | 知识聚类/主题 | — |

### 自动化 Pipeline
| 工具 | 说明 | 必填参数 |
|------|------|---------|
| `kb.extract` | 知识提取 (Two-Step CoT) | kb_id |
| `kb.evolve` | 关系发现/聚类 | kb_id |
| `kb.crystallize` | 结晶生成 | kb_id |
| `kb.lint` | 健康检查 | kb_id |
| `kb.import` | 导入目录到 raw | kb_id, source_path |

### 任务与监控
| 工具 | 说明 | 必填参数 |
|------|------|---------|
| `kb.dashboard` | 汇总视图 | — |
| `kb.jobs` | 任务状态/列表 | — |

## 设计模式

参考 Nowledge Mem 的层次化设计：

```
Nowledge Mem         →  LLMWiki MCP
─────────────────────────────────────
/memories (memory_*) →  kb.search / kb.read / kb.write
/sources             →  kb.import / kb.read
/wiki                →  kb.index / kb.read
/graph               →  kb.graph / kb.communities
/crystals            →  kb.crystals
/working-memory      →  kb.dashboard / kb.status
```

所有工具支持可选的 `kb_id` 参数。不传则默认使用 API 当前激活的知识库。
