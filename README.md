<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="archive/brand/guixu-mark.svg">
    <img src="archive/brand/guixu-mark-dark.svg" alt="归墟" width="120">
  </picture>
</p>

<h1 align="center">归墟 · 数据处理 Agent</h1>

<p align="center">
  用一句中文，处理你的数据。<br>
  <sub>Windows 10/11 x64 · 本地优先 · 数据库留在本机</sub>
</p>

归墟是一个本地运行的数据处理 Agent。把 Excel 拖进来，用自然语言提问、修改、导出或写文档；它会生成 SQL、展示候选、等你确认，再把结果和产物放回同一个工作台。

不是聊天框套一个数据库，而是一个能看见每一步的桌面工具：工具调用、思考过程、确认卡片、执行轨迹都摊在界面上。

## 能做什么

- **查询**：「上个月新增了多少条记录」→ 生成 SQL、执行、回答；数据字典里声明了关联时，可以按关联做一跳 JOIN
- **增删改**：单条或批量；删除是软删除，进回收站，确认后才执行
- **导入导出**：扫描 Excel 与库的差异（新记录 / 冲突 / 已删除），确认后导入；导出中文列名的 Excel
- **规则重塑**：「所有计数加 1」「某一列去掉首尾空格」→ 生成预览、确认、批量执行
- **结构变更**：加列、改列、删列、建表、删表；破坏性操作前自动落快照
- **报表与文档**：日/周/月报（统计、图表、环比、PDF）；也可以让它写 PDF / Word / Markdown / txt
- **文档库**：上传 PDF / Word / txt / md，自动解析、分块、向量化；对话里用 `search_documents` 检索制度和手册

## 安装

### 安装包（推荐）

从 [GitHub Releases](https://github.com/niannian-Gzh/GuiXu-DataPilot/releases) 下载最新版：

```text
GuiXu-Setup-1.2.0.exe
```

双击安装即可。默认装到 `%LOCALAPPDATA%\Programs\GuiXu`，**不需要管理员权限**；用户数据在 `%LOCALAPPDATA%\GuiXu`，和安装目录分开，卸载不会删除。

安装包未做代码签名，Windows SmartScreen 可能提示“未知发布者”；选择“更多信息 → 仍要运行”即可。

**环境要求**：Windows 10/11 x64；界面依赖系统 WebView2（Win11 预装，Win10 通常随 Edge 更新下发）；PDF 依赖系统 Edge。

### 从源码运行

需要 Python 3.12+ 和 [uv](https://github.com/astral-sh/uv)：

```bash
git clone https://github.com/niannian-Gzh/GuiXu-DataPilot.git
cd GuiXu-DataPilot
uv sync

# 文档库的 embedding 权重（约 91MB，只需一次；不进版本库）
uv run python scripts/fetch_model.py

# 浏览器开发模式
uv run uvicorn api:app --app-dir src
# 打开 http://127.0.0.1:8000

# 桌面窗口模式
uv sync --extra desktop
uv run python src/desktop.py
```

### 自己打包安装包

需要 [Inno Setup 6](https://jrsoftware.org/isinfo.php)（`ISCC.exe`）：

```bash
uv sync --extra desktop --group build
uv run python scripts/build_app.py              # 文件夹版 dist/GuiXu/
uv run python scripts/build_app.py --installer  # 安装包 dist/GuiXu-Setup-1.2.0.exe
```

## 第一次使用

首次启动会在开机动画里让你填模型配置：

1. 选择供应商
2. 粘贴 API Key
3. 失焦后自动拉取可用模型，选一个（也可以直接手打模型名）
4. 点「验证并接入」；通过后写入 `%LOCALAPPDATA%\GuiXu\configs.json`，Key 单独写进 `secrets.json`

配置和密钥都不进安装目录，也不会随安装包分发。之后可以在设置页切换模型、调整参数。

新建的库是空的（0 表 0 字段），这是正常状态。在界面上传一个 Excel，Agent 会先推测它对应哪张表、和已有表有没有关系，确认后建表并导入。

## 设计

**Agent Loop**：模型返回 `tool_calls` 就执行工具、把结果放回消息、继续循环；没有就返回最终答案。核心循环不到 100 行。

**20 个工具**，按性质分四类：读 / 写 / 结构 / 产出。工具只做“菜单 + 传话筒”，业务逻辑在 `services/`；加功能 = 加 service + 注册工具。

**确认与中断**：`ask_user` 和确认卡片是同一种机制——工具挂起，用户回应，工具拿到回应继续。断点存在会话里，跨轮次续跑；增删改、导入、改结构执行前都要确认。

**数据层**：SQLite 单文件。业务表通过视图 + `INSTEAD OF` 触发器做软删除隔离；审计写进 `_gx_audit`，和业务写入同一个事务；破坏性操作前落快照，可回滚。

**文档库**：切片原文和向量存 SQLite（唯一真源），FAISS 只是内存派生索引，数据变更后重建。扫描件 PDF 没有文字层时，页面转 PNG 交给当前多模态模型识别；模型不支持图片会明确报错。

**防护**：只读 SQL 在执行前过闸门；表名白名单防止绕过视图读底表；LLM 重试、思维熔断、异常熔断、SQL 超时、Loop 总超时分层兜底。

## 评测

**182 条用例，九个维度**：

- **离线 142 条**：不调模型，秒级。注入与越权、边界、并发、审计与快照、文档入库/软删/恢复、扫描件、四种产物、结构升级与备份
- **Agent 40 条**：真调模型。20 个工具、确认/取消/跳过、提示注入、文档检索、不编造

```bash
uv run python eval/run.py --suite offline   # 免费，随便跑
uv run python eval/run.py --suite agent     # 需要可用 key
```

期望值从 fixture 现算，不硬编码；每条用例一个临时库，不碰真实数据。攻击用例的判据是三件事同时成立：**被拒绝 + 数据零变化 + 该保护的还在**。

最近一次结果：离线 **142/142**；Agent **39/40**，失败项是模型偶发生成了一条被只读闸门拒绝的 SQL，单独复跑通过。详见 [eval/README.md](eval/README.md)。

## 数据与升级

| 位置 | 内容 |
|---|---|
| `%LOCALAPPDATA%\Programs\GuiXu` | 程序文件（安装目录） |
| `%LOCALAPPDATA%\GuiXu` | 配置、密钥、数据库、导出、报告、上传、文档、会话、日志 |
| `%LOCALAPPDATA%\GuiXu\data\guixu.db` | 数据库（SQLite 单文件） |
| `%LOCALAPPDATA%\GuiXu\data\backups` | 升级前的数据库备份（保留最近 3 份） |

安装新版时只替换程序文件，用户数据不动。数据库结构用 `PRAGMA user_version` 标记；迁移前自动备份，迁移在事务里执行、只增不删；库比程序新时拒绝打开，避免旧版本硬改新数据。

归墟没有自有云服务。数据库、文件、会话都在本机；模型调用会把你配置的 API 所需的上下文（问题、SQL、结果行）发给你选择的模型服务商。关于页的「检查更新」是手动的：只有点按钮才访问 GitHub Releases，只比较版本并给下载页，不自动下载、不自动安装。

## 已知限制

- **跨表关联只支持一跳**：查询主表时会把数据字典里直接关联的表结构带进 prompt，可以 JOIN 这些表；两跳以上或任意多表仍未支持
- **无权限控制**：单用户本地应用，所有能打开数据目录的人看到相同数据
- **扫描件依赖模型视觉能力**：当前模型不支持图片输入时会明确报错，需要换配置
- **FAISS 索引在内存**：启动或数据变更后重建；它只是派生物，切片原文始终在 SQLite
- **工具返回存的是截断版**（8000 字符）：超长结果在历史会话里回看时不全
- **Word 预览只保留内容结构**：标题 / 段落 / 表格，不还原字体、字号、行距
- **PDF 依赖系统 Edge**：Edge 被卸载或损坏时会明确报错，不影响其余功能
- **无边框窗口不支持拖边缩放**：可以最大化/还原，窗口有最小尺寸 1024×680
- **安装包未签名**：SmartScreen 会提示；更新也不会自动下载安装

## 项目结构

```text
src/
├── api.py / desktop.py      FastAPI 入口 / 桌面窗口入口
├── agent.py / tools.py      Agent Loop / 20 个工具
├── storage.py / runner.py   SQLite 结构、软删隔离 / 连接、事务、超时
├── snapshot.py             快照与回滚
├── migrations.py           数据库结构版本与迁移（schema 1 基线）
├── services/               业务逻辑（CRUD、导入导出、报告、文档）
├── rag/                    文档解析、分块、embedding、FAISS、检索
└── web/static/             前端（Vue 3 + marked，无构建步骤）

scripts/                    fetch_model.py · build_app.py
packaging/                  PyInstaller spec · Inno Setup 脚本
eval/                       182 条评测
models/                     embedding 权重（gitignore，打包时随安装包）
```

分层与每条决策的来龙去脉见 [archive/docs/design.md](archive/docs/design.md) 和 [archive/docs/decisions.md](archive/docs/decisions.md)。

## 声明

- **开机动画**：参考并改自 [dsh-startup-screen](https://github.com/6shenhonghong9/dsh-startup-screen)（作者：[6shenhonghong9](https://github.com/6shenhonghong9)），MIT License，Copyright (c) 2026 沈宏宏。原项目的版权与许可声明保留在 `src/web/static/js/boot.js` 和 `src/web/static/css/splash.css` 的文件头；完整许可见[上游 LICENSE](https://github.com/6shenhonghong9/dsh-startup-screen/blob/main/LICENSE)。本项目替换了标识、素材与时序。
- **人声播报**：`src/web/static/audio/line-*.mp3` 由本项目使用 Microsoft Edge TTS（[edge-tts](https://github.com/rany2/edge-tts)）的 **Ava 英文女声**导出；界面音效由 WebAudio 现场合成
- **联系方式**：3401835026@qq.com

## 许可证

MIT，见 [LICENSE](LICENSE)。
