# ObWiki 用户指南 v0.2.0

## 安装与启动

### 前置条件

- **Docker**：[OrbStack](https://orbstack.dev)（macOS）或 Docker Desktop（Win/Linux）
- **Obsidian** ≥ 1.5.0

### 第一步：安装插件

1. 下载 `plugin/` 目录，完整复制到 vault 的 `.obsidian/plugins/obwiki/`
2. 打开 Obsidian → 设置 → 第三方插件 → 启用 ObWiki

### 第二步：启动服务

1. 打开 ObWiki 设置 tab
2. 点击「复制命令并生成配置」
3. 打开终端（Terminal），粘贴命令，回车
4. 等待首次构建（2-3 分钟）
5. 回到插件，点「刷新状态」，应显示「运行中 — v0.2.0」

### 第三步：配置 LLM

1. 设置 tab → 模型供应商 → 添加
2. 选择服务商（DeepSeek / OpenAI / 阿里云）→ 填入 Base URL 和 API Key
3. 点击「检测模型」→ 选择默认文本模型 → 点击「应用」

### 第四步：创建知识库

1. 知识库 tab
2. 名称：给知识库起名
3. 路径：自动填入当前 vault 路径（可通过下拉选择子目录）
4. 确认显示「🔗 路径映射: /data/kbs」
5. 点击「创建并初始化」→ 等待 1 秒 → 点击「激活」

---

## 面板说明

### Dashboard（仪表盘）

- 顶部 6 个卡片：文档待处理 / 处理中 / Wiki页数 / 全局任务 / Token用量 / 图谱关系
- **文档处理队列**：显示前 4 个排队文档，右上角「打开队列」查看全部
- **全局任务**：所有已完成/失败/运行中的任务历史

### 操作 tab

- **导入**：拖放文件 / 从 vault 选择文件或文件夹 / 直接丢文件到 `_inbox/`
- **知识库操作**：文档处理（scan→organize→extract） / 知识演进 / 生成结晶 / 检测社区
- **质量检查**：检查（lint 质量审计）/ 自动修复（补 frontmatter + 清除断链）
- **查重与审核**：检测重复 + 审核合并

### 知识库 tab

- 查看当前 vault 下的所有知识库（过滤显示）
- 新建知识库：自动路径映射 + vault 目录选取
- 激活 / 删除（仅从注册表移除，不删文件）

### 设置 tab

- **服务管理**：状态 + 复制启动命令 + 刷新状态
- **API 地址**：默认 `http://127.0.0.1:8742`
- **MCP 接入**：复制配置 JSON 到 AI 工具
- **模型供应商**：添加/删除/设为默认/检测模型
- **Token 限额**：每日限额（0 = 不限）

### 自动化 tab

- 四个定时任务：收件箱整理 / 文档处理 / 知识演进 / 健康检查
- 可设置 daily/weekly/off + 时间

---

## 使用流程

### 日常：导入知识

1. 拖放文件（PDF/Word/Markdown/TXT 等）到插件面板
2. 自动触发文档处理（或手动点）
3. 等待完成（2-5 分钟/文档，Dashboard 可看到进度）

### 进阶：知识整理

当 wiki 积累到 5+ 页后：

1. 点击「知识演进」→ LLM 发现关系 + Louvain 层次聚类
2. 点击「生成结晶」→ LLM 从每个聚类生成深度合成文档
3. 点击「检测社区」→ 生成 hub 页面（[[wikilinks]] 索引）

### AI 辅助：MCP 接入

Cherry Studio / Claude Code 等支持 MCP 的工具：

1. 设置 tab → 复制 MCP 配置
2. 粘贴到 MCP client 配置文件
3. AI 可以：搜索知识 / 读取页面 / 浏览链接关系 / 导入新内容 / 触发知识演进

---

## 常见问题

**Q: 启动服务后状态显示"已停止"**
A: 确认终端命令没报错。检查 Docker 是否运行、端口 8742 是否被占用。

**Q: 点了文档处理没反应**
A: 检查是否配了 LLM（设置 → 模型供应商必须至少有一个）。检查全局任务是否显示「LLM_NOT_CONFIGURED」。

**Q: 知识库路径显示"Docker 路径"太长**
A: 插件自动映射，知识库面板已还原为本地路径显示。Dashboard 只展示本地路径。

**Q: MCP 连接失败**
A: 确保 Docker 运行中。MCP URL 为 `http://127.0.0.1:8742/mcp/sse`。

**Q: Token 消耗太快**
A: 设置「每日 Token 限额」控制全局用量。到达限额后 LLM 任务自动停止。

---

## 目录结构

```
vault/
├── _inbox/           原始导入文件（含分类子目录）
├── _meta/            元信息（index / overview / schema）
├── wiki/             LLM 生成的知识页面
│   ├── sources/      源文档摘要（含原文）
│   ├── entities/     实体页面
│   ├── concepts/     概念页面
│   ├── crystals/     结晶笔记
│   └── ...
├── communities/      社区 hub 页面（层次结构）
├── operations/       操作日志 + lint 报告
└── .obsidian/plugins/obwiki/   插件目录（含 Docker 配置）
```
