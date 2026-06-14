# ObWiki

LLM 驱动的本地知识引擎——将 Obsidian vault 变成结构化的 AI 可操作知识库。

```
Obsidian 插件  ←→  Docker API 引擎  ←→  MCP Server (HTTP)
        │                │                    │
        └────────────────┼────────────────────┘
                         │
                  知识库目录 (markdown + SQLite + FTS5)
```

## 安装

1. **装 Docker**：[OrbStack](https://orbstack.dev)（macOS 推荐）或 Docker Desktop
2. **装插件**：复制 `plugin/` 到 `.obsidian/plugins/obwiki/`，在 Obsidian 中启用
3. **启动服务**：打开插件设置 → 点"复制命令并生成配置" → 在终端粘贴运行 → 等待首次构建完成
4. **配 LLM**：插件设置 → 模型供应商 → 添加（DeepSeek/OpenAI 等）
5. **创建知识库**：知识库 tab → 填名称 → 路径自动填入 → 创建并初始化 → 激活

## 快速使用

- **导入知识**：拖放文件到插件面板，点"文档处理"
- **知识演进**：积累 5+ wiki 页后点"知识演进"→"生成结晶"→"检测社区"
- **MCP 接入**：设置 tab → 点"复制配置" → 粘贴到 AI 工具

## 管线

```
_inbox/ (源文件)
  └→ 文档处理 (scan → organize → extract)
       └→ LLM 提取 → wiki/*.md
              │
  ┌───────────┘
  └→ 知识演进 (evolve) → Louvain 层次聚类
       ├→ 生成结晶 (crystallize)
       └→ 检测社区 (communities)
```

## MCP 工具

24 个 MCP 工具，Docker 内置 SSE HTTP 端点。覆盖：查询（search/read/browse）、导入（ingest/import）、管线（evolve/crystallize/communities）。

## 项目结构

```
├── api/              Python 后端 (FastAPI)
├── plugin/           Obsidian 插件 (含 Docker 配置)
├── mcp/              MCP Server (Python, 已集成到 API)
├── README.md
├── DESIGN.md         设计文档
└── USER_GUIDE.md     用户指南
```

## License

MIT © Franvz9
