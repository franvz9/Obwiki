# ObWiki 设计文档 v0.2.0

## 架构

```
┌─────────────┐     HTTP      ┌──────────────┐     stdio/SSE     ┌───────────┐
│  Obsidian   │ ←──────────→ │  API Engine  │ ←──────────────→ │ MCP Server│
│   Plugin    │   :8742       │  (FastAPI)   │    /mcp/sse      │  (Docker) │
└─────────────┘               └──────┬───────┘                  └───────────┘
                                     │
                              SQLite + FTS5
                                     │
                              KB 目录 (markdown)
```

- **插件**：TypeScript，Obsidian API，Docker 生命周期管理
- **API**：Python/FastAPI，异步任务队列，多供应商 LLM
- **MCP**：Python/FastMCP，SSE HTTP 传输，24 个工具
- **Docker**：统一部署，挂载 vault 目录，数据卷持久化

## 服务清单

| 服务 | 文件 | 职责 |
|------|------|------|
| KBRegistry | `kb_registry.py` | KB CRUD + 目录初始化 |
| SourceRegistry | `source_registry.py` | 源文件生命周期（raw→indexed→...→extracted） |
| Scanner | `scanner.py` | 文件扫描 + FTS5 索引（含 wiki 页面） |
| Extractor | `extractor.py` | LLM 两步知识提取（ANALYSIS→GENERATION） |
| Evolver | `evolver.py` | LLM 关系发现 + Louvain 层次聚类 + 软分配 |
| Crystallizer | `crystallizer.py` | 集群过滤（≥5页+≥75%凝聚度）+ LLM 结晶合成 |
| CommunityGenerator | `community_gen.py` | 层次社区 hub 页生成 |
| Linter | `linter.py` | 质量审计 + 自动修复（frontmatter/断链） |
| Organizer | `organizer.py` | 规则文件分类 |
| MergeDetector | `merge_detector.py` | 重复检测（同类型，CN-EN 识别，LLM 判定） |
| JobRunner | `job_runner.py` | 异步任务队列（Semaphore 限流） |
| JobScheduler | `scheduler.py` | 定时任务 + 自动演化（wiki 变化→10min→auto） |
| TokenTracker | `token_tracker.py` | LLM 调用 token 计数 |
| LLMClient | `llm.py` | 多供应商 LLM 客户端 |
| WikiSchema | `wiki_schema.py` | Schema.md 解析 |

## 管线设计

### 文档处理（process: scan→organize→extract）

| 步骤 | 服务 | LLM |
|------|------|:---:|
| scan | Scanner：遍历 _inbox_，解析文件，注册 SourceRegistry，FTS5 索引 | - |
| organize | Organizer：规则分类，移动到子目录 | - |
| extract | Extractor：两步 LLM：ANALYSIS_PROMPT（结构化分析）→ GENERATION_PROMPT（生成 wiki 页面 + _meta 文件） | 是 |

### 知识整理（evolve→crystallize→communities）

| 步骤 | 服务 | LLM |
|------|------|:---:|
| evolve | Evolver：批处理 LLM 发现页面关系 → Louvain 层次社区检测 + 软分配 → LLM 批量命名 | 是 |
| crystallize | Crystallizer：集群过滤 + 去重 → 每集群一次 LLM 合成 | 是 |
| communities | CommunityGenerator：读 clusters.json → 层次目录 hub 页 | - |

### 质量检查（lint/repair）

| 步骤 | 服务 | LLM |
|------|------|:---:|
| lint | Linter：抽样 15 页 → LLM 7 项审计 → 保存 lint_report.json | 是 |
| auto_fix | Linter：补 frontmatter + 清除断链 | - |

## 聚类算法

Louvain 层次社区检测 + 软分配：

1. LLM 分析 wiki 页面，生成 edges（supports/extends/contradicts 等 7 种关系 + 加权）
2. 构建加权无向图
3. Louvain 社区检测 → L1 社区
4. 每个 L1 社区 ≥6 节点 → 子图 Louvain → L2，递归至 L3
5. 软分配：节点对某社区的边权重 >20% → 也归属该社区
6. LLM 批量命名所有层级社区

## 合并检测

同类型比较（community/crystal），规则：

| 条件 | 动作 |
|------|------|
| 中英同义（overlap >15%） | 加入审核队列 |
| <35% 词重叠 | 跳过 |
| 35-50% | LLM 判定 merge/review/skip |
| >50% | 自动合并（保留新文件） |

## 缓存策略

| 服务 | 缓存键 | 行为 |
|------|--------|------|
| evolve | wiki 页面指纹（SHA256 of paths+sizes） | 匹配 → 跳过 LLM，token=0 |
| community | clusters.json 哈希 | 匹配 → 跳过生成 |
| crystallize | clusters.json 哈希 | 匹配 → 跳过合成 |

## 自动化

- **定时任务**：organize/process/evolve(→crystallize→communities)/lint，可配置 daily/weekly
- **自动演化**：wiki 结构变化 → 指纹记录 → 10min 冷却 → 无新变化 → 自动 evolve→crystallize→communities
- **并发控制**：Semaphore(2) 限流

## Token 追踪

`TokenTracker` 模块统一管理所有 LLM 调用，避免重复计数。

## 搜索

### FTS5 全文搜索
- SQLite FTS5 + unicode61 tokenizer
- 索引 `_inbox/` 文件 + `wiki/` 页面内容
- 支持分页（offset/limit）

### 语义搜索（LLM 重排）
1. FTS5 初筛 20 条
2. LLM 按相关度打分（0-100）+ 理由
3. 返回 top N

## API 路由摘要

| 路径前缀 | 用途 |
|---------|------|
| `/v1/kbs` | KB CRUD + 初始化 + 激活 |
| `/v1/kbs/{id}/import` | 导入（upload/file-content/folder-json） |
| `/v1/kbs/{id}/jobs` | 任务触发（process/extract/evolve/crystallize/communities/lint/organize/scan） |
| `/v1/kbs/{id}/dashboard` | 统计汇总 |
| `/v1/kbs/{id}/search` | FTS5 搜索 |
| `/v1/kbs/{id}/search/semantic` | LLM 重排语义搜索 |
| `/v1/kbs/{id}/review-items` | 重复审核 |
| `/v1/kbs/{id}/documents` | 文档队列 |
| `/v1/kbs/{id}/schedule` | 定时任务配置 |
| `/v1/jobs/{id}` | 任务状态 |
| `/v1/providers` | LLM 供应商管理 |
| `/health` | 健康检查 |
| `/v1/config` | 服务端配置（客户端自动发现） |
| `/mcp/sse` | MCP SSE 端点 |

## 页面类型

| 类型 | 目录 | 命名 |
|------|------|------|
| source | wiki/sources/ | source-name.md |
| entity | wiki/entities/ | PascalCase.md |
| concept | wiki/concepts/ | kebab-case.md |
| comparison | wiki/comparisons/ | a-vs-b.md |
| synthesis | wiki/synthesis/ | topic-name.md |
| finding | wiki/findings/ | finding-name.md |
| thesis | wiki/thesis/ | thesis-name.md |
| methodology | wiki/methodology/ | method-name.md |
| crystal | wiki/crystals/ | crystal-name.md |
| query | wiki/queries/ | query-name.md |

## 环境变量

| 变量 | 用途 |
|------|------|
| `LLMWIKI_KB_ROOT` | vault 路径挂载 |
| `LLMWIKI_PORT` | 服务端口（默认 8742） |
| `LLMWIKI_DB_PATH` | SQLite 路径 |

> LLM 配置通过插件 UI 管理，无需环境变量。

## License

MIT © Franvz9
