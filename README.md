# ObWiki

> 一个基于 LLM 的本地化、轻量型、自我生长的知识引擎。
> 受 [Karpathy 的 LLM Wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) 启发。

### 和 RAG 有什么不同？

RAG 每次查询都要重新检索和组织知识，而 ObWiki 一次性将知识**结构化写入文件系统**——markdown 页面 + `[[wikilinks]]` 连接 + YAML frontmatter + FTS5 索引。知识一旦提取，就永久沉淀为可读、可编辑、可演进的结构化文档，不需要每次重新"组装"。

### 和数据库型知识库有什么不同？

ObWiki 的每一页知识都是一个真实的 `.md` 文件。你可以直接在 Obsidian 中打开编辑、修改 frontmatter、调整 `[[wikilinks]]`。文件即数据，不像数据库那样把知识锁在黑盒里。

### 自我生长与演进

- **文档处理管线**：导入文件 → LLM 提取实体/概念/论据 → 生成结构化 wiki 页面
- **Louvain 层次聚类**：LLM 发现页面间关系 → 图算法自动分簇 → 形成多层知识社区
- **结晶合成**：LLM 从每个聚类合成高置信度的深度知识笔记
- **自动演化**：wiki 结构变化后自动触发演进，知识库持续自我更新

### AI 的长期记忆

ObWiki 可以作为 AI 对话的持久记忆层。AI 调用的每次思考、每次查找结果、每次生成内容，都可以通过 MCP 工具写入知识库并与其他知识连接。记忆不是孤岛，而是随着对话的积累持续生长、演进、自我整理的有机整体——永久化的、可查询的、会自我组织的第二大脑。

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
