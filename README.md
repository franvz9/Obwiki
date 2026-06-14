# ObWiki v0.2.0

LLM 驱动的本地知识引擎。将 Obsidian vault 变成 AI 可操作的结构化知识库。

```
Obsidian 插件  ←→  Docker API (8742)  ←→  MCP Server (stdio)
        │                │                    │
        └────────────────┼────────────────────┘
                         │
                  知识库目录 (markdown + SQLite + FTS5)
```

## 安装

1. 装 Docker（macOS 推荐 [OrbStack](https://orbstack.dev)）
2. 将 `plugin/` 复制到 `.obsidian/plugins/obwiki/`
3. 启用插件 → 设置 tab → 生成配置并复制命令 → 终端运行
4. 配 LLM（设置 → 模型供应商 → 添加）
5. 创建知识库（自动 scan 索引已有内容）

## 管线

```
_inbox/ → 文档处理 (scan→organize→extract) → wiki/ 
   → 知识演进 (Louvain 层次聚类) → 结晶 + 社区
```

## MCP 工具

24 个 MCP 工具（stdio），覆盖搜索/读取/导入/管线触发。

## License

MIT © Franvz9
