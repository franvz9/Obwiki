# ObWiki 用户指南 v0.2.0

## 安装（三步）

### 1. 装 Docker

- macOS：安装 [OrbStack](https://orbstack.dev)（免费，推荐）
- Windows/Linux：安装 [Docker Desktop](https://docker.com)

### 2. 装插件

将 zip 解压后的整个文件夹内容复制到 vault 的 `.obsidian/plugins/obwiki/`，启用。

### 3. 启动服务

1. 打开 ObWiki 设置 tab
2. 点击「生成配置并复制命令」
3. 打开终端 → 粘贴 → 回车
4. 等待首次构建（2-3 分钟，后续秒启）
5. 点「刷新状态」→ 显示"运行中 — v0.2.0"

---

## 配置 LLM

设置 tab → 模型供应商 → 添加：
- 选择服务商（DeepSeek / OpenAI / 阿里云）
- 填入 Base URL 和 API Key
- 点击「检测模型」→ 选默认模型 → 应用

> 配置立即生效，无需重启。

---

## 创建知识库

1. 知识库 tab
2. 填名称 → 路径自动填入 vault 路径（可选子目录）
3. 确认显示「路径映射: /data/kbs」
4. 点击「创建并初始化」
5. 点击「激活」

> 初始化会自动扫描已有 wiki 页面并建立搜索索引。

---

## 日常使用

### 导入知识

- 拖放文件到 ObWiki 面板
- 或从 vault 选择文件/文件夹导入
- 或直接丢文件到 `_inbox/` 目录
- 点「文档处理」（或等后台自动处理）

### 整理知识

当 wiki 积累到 5+ 页：
1. 点击「知识演进」→ 发现关系 + 聚类
2. 点击「生成结晶」→ 深度合成
3. 点击「检测社区」→ 生成索引页

### MCP 接入

设置 tab → 复制 MCP 配置 → 粘贴到 Cherry Studio / Claude Code。24 个工具覆盖搜索、读取、导入、管线触发。

---

## 面板一览

| Tab | 功能 |
|-----|------|
| Dashboard | 文档队列 + 全局任务 + Token 用量 |
| 操作 | 导入 + 知识库操作 + 质量检查 + 查重审核 |
| 知识库 | 创建/激活/删除（不删文件） |
| 自动化 | 四个定时任务（daily/weekly/off） |
| 设置 | 服务管理 + LLM 供应商 + Token 限额 + MCP 配置 |

---

## 目录结构

```
vault/
├── _inbox/           导入文件（含分类子目录）
├── _meta/            元信息
├── wiki/             LLM 生成的知识页
│   ├── sources/      源文档摘要（含原文）
│   ├── entities/     实体
│   ├── concepts/     概念
│   ├── crystals/     结晶
│   └── ...
├── communities/      社区 hub 页
├── operations/       日志 + 报告
└── .obsidian/plugins/obwiki/  插件 + Docker 配置
```

## 常见问题

- **启动后显示"已停止"**：检查 Docker 是否运行，端口 8742 是否被占用
- **管线任务提示 LLM_NOT_CONFIGURED**：去设置 tab 添加模型供应商
- **搜索无结果**：初始化后会自动 scan，如果之前跳过了，点「文档处理」即可
- **MCP 连接失败**：确保 uv 已安装（`curl -LsSf https://astral.sh/uv/install.sh | sh`）
- **Token 消耗快**：设置「每日限额」控制
