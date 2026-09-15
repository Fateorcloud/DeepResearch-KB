# DeepResearch-KB Web 与云端互通开发方案

状态：实施中。Stage 0～4 已于 2026-09-15 完成 Gate，下一阶段为 Stage 5 Deployment。本文描述产品层开发，不改变 Phase 1～5B 已验收的 Research Core。

## 1. 目标

为单用户提供一个简洁、可长期使用的 Web 研究工作台：在任意网络和设备上登录后，可以管理知识库、上传和查看文档、运行真实 Research、检查报告与证据，并下载一致性备份。本地控制端负责扫描本机目录和推送原文件，云端负责保存唯一权威数据。

```text
本地文件夹                         任意设备浏览器
    │                                    │
    ↓                                    ↓
Local Control Web ─── HTTPS ───→ Cloud DeepResearch-KB
    │                                    │
 ingest / push                      login / KB / research
                                         │
                                Authoritative SQLite
                                + Research Artifacts
                                         │
                                backup / archive export
```

## 2. 核心原则

1. 云端 SQLite 是唯一权威知识库，不维护需要合并的本地、云端双主数据库。
2. 本地向云端传输原文件、`logical_path` 和必要 metadata，不直接覆盖云端 `.db`。
3. 云端数据库可生成一致性快照并下载到本地备份；备份不是双向同步。
4. Web、CLI、MCP 继续复用 `KnowledgeService`、`ResearchService` 和 `TaskService`。
5. 不修改版本治理、充分性判断、Adaptive Router 或 Phase 4.5 冻结评测。
6. 初期仅支持单用户，认证实现仍满足基本 Web 安全要求。

## 3. 当前事实与接线缺口

当前已有：

- `KnowledgeStore`、版本治理和统一 ingest contract；
- `KnowledgeService`、`ResearchService`、`TaskService`；
- KB 创建/列表、Web Upload、文档/版本查询；
- `ingest-dir`、`push-dir`；
- `ResearchEngine` 和 CLI 真实 Research；
- MCP facade 与真实 stdio transport smoke。

开始前必须补齐：

- 默认 FastAPI 尚未装配真实 `ResearchService`，`POST /api/research` 当前会返回 503；
- `ResearchService` 尚未向 `ResearchEngine` 传递显式 `EvidenceRequirement`；
- 缺少 KB 重命名、文档内容预览、认证和一致性备份接口；
- 浏览器不能直接扫描任意本地目录，本地一键操作需要 loopback companion。

这些属于 composition、product contract 和 integration，不要求重写 Research Core。

## 4. 数据权威与互通

### 4.1 首次迁移

首次部署通过 SQLite online backup 或停机复制，将当前 `data/kb.sqlite` 导入服务器持久化 volume。迁移后校验：

- `PRAGMA integrity_check`；
- KB/document/version/chunk 数量；
- 当前版本与 provenance；
- 一次 governed retrieval。

### 4.2 日常推送

本地控制端调用上传接口：

```text
relative logical_path + bytes + source metadata
              ↓
        KnowledgeService.ingest
              ↓
same hash = unchanged / changed hash = version + 1
```

`kb_id + logical_path` 决定文档身份；重命名 KB 不改变 `kb_id`。首版不传播本地删除，不实现冲突合并或双向实时同步。

### 4.3 云端备份

数据库下载必须使用 SQLite backup API 创建一致性临时快照，不能直接读取正在写入的数据库文件。下载流程：

```text
authenticated request → online backup → integrity check
→ timestamped .sqlite response → staging cleanup
```

另提供完整归档导出，包含：

```text
kb.sqlite
tasks/
manifest.json
```

首版恢复只提供服务器 CLI，不提供公网网页一键覆盖数据库。

### 4.4 三种入口与数据库边界

| 入口 | 连接对象 | 可写数据 | 不应做的事 |
|---|---|---|---|
| Cloud Web | 云端 API → 云端 `kb.sqlite` | KB、文档版本、Research task 请求 | 直接访问 SQLite 文件 |
| Local Control Web | loopback companion → 云端 API | 扫描本地目录、上传原文件、请求备份 | 上传/覆盖数据库，建立双主同步 |
| MCP | 应用 Service Layer | 复用云端或明确配置的单一 `KnowledgeStore` | 创建 MCP 专属库或自行复制 Research 逻辑 |

云端持久化分为三类：`kb.sqlite` 是唯一知识库权威；`tasks/` 保存 Research artifacts；
`backups/` 保存通过 online backup 生成的下载副本。Local Control 的可选 `local.sqlite`
仅服务本地 `ingest-dir` 验证，不是云端副本，也不参与合并。MCP 部署在云端时与 Web
共享同一 Service Layer 和云端数据库；本地运行 MCP 时必须显式指定一个数据库路径，
不提供隐式的本地/云端双主关系。

## 5. 单用户认证

- 一个固定管理员账号，无注册入口；
- 密码仅以 Argon2 hash 保存；
- 浏览器使用 `HttpOnly + Secure + SameSite=Lax` session cookie；
- 修改请求使用 CSRF token；
- CLI/local companion 使用独立 Bearer token；
- token 可轮换和吊销，不与登录密码复用；
- 登录限速，失败响应不暴露账号是否存在；
- provider key、session secret 和 token 仅存在服务器环境变量；
- 除登录、静态资源和健康检查外，所有 route 均需认证。

Local Control 的 `DRKB_CLI_TOKEN` 来自云端 Web“设置 → CLI / Local Control token”创建动作，
明文只展示一次；它不是登录密码，也不应写入仓库或公开命令历史。

## 6. 后端 product contract

### 6.1 Knowledge

- `POST /api/kbs`：创建知识库；
- `GET /api/kbs`：列表与概览；
- `PATCH /api/kbs/{kb_id}`：重命名，保持 ID 不变；
- `POST /api/kbs/{kb_id}/documents`：上传；
- `GET /api/kbs/{kb_id}/documents`：文档列表；
- `GET /api/kbs/{kb_id}/documents/{document_id}`：metadata 与解析内容节选；
- `GET /api/kbs/{kb_id}/documents/{document_id}/versions`：版本时间线；
- `GET /api/kbs/{kb_id}/documents/{document_id}/versions/{version}`：指定版本内容与 provenance。

页面首版显示“解析内容预览”，不称为 AI 摘要。`.db` 不是支持的普通知识文档格式。

### 6.2 Research

`POST /api/research` 接收：

- query；
- `knowledge_base_ids`；
- required claims；
- required source types；
- minimum distinct sources；
- require current version；
- 可选 as-of；
- max Deep calls。

返回 `task_id`，客户端轮询状态。完成后读取 report、sources、trace 和 metrics。页面把 EvidenceRequirement 翻译成用户语言：

- 报告必须回答什么？
- 是否必须使用内部资料？
- 是否需要外部来源？
- 至少需要几个独立来源？
- 是否只允许当前版本？

### 6.3 Backup

- `POST /api/backups`：生成一致性备份；
- `GET /api/backups/{backup_id}`：下载；
- `POST /api/exports`：生成数据库与 research artifacts 完整归档。

所有下载均需认证，不在响应或文件名中包含 secret。

## 7. 本地控制端

浏览器不能安全地自行执行本地 CLI。因此提供 loopback-only companion：

```sh
deepresearch_kb local-web \
  --root /allowed/local/root \
  --server https://research.example.com
```

约束：

- 仅监听 `127.0.0.1`；
- 只能访问 `--root` 下的路径；
- 直接调用 Python module，不拼接 shell 命令；
- 云端 token 存在操作系统凭据存储或本地权限受限配置中；
- 支持目录扫描、`ingest-dir`、`push-dir`、结果汇总和备份下载；
- 本地页面与云端页面共用视觉语言，但职责和运行位置明确区分。

## 8. Web 信息架构

技术栈建议：React、TypeScript、Vite、React Router、TanStack Query、Zod、CSS Modules、Lucide icons。建立独立 `web/`，不修改 upstream `frontend/nextjs`。

### 页面

1. 登录：单用户登录，无注册入口。
2. 首页：Research composer、知识库概览、最近研究、当前版本活动、Evidence pathway。
3. 知识库详情：重命名、拖拽上传、文档列表、内容预览、版本时间线、provenance。
4. Research Composer：问题、KB 选择、Evidence Contract 高级设置。
5. Research Result：报告、Sources、Route Trace、Version Decisions、Metrics。
6. 设置与备份：下载数据库/完整归档、CLI token 管理、provider 可用状态；不回显完整 secret。

### 视觉方向

保留方案 2 的信息结构。首页研究输入区使用大尺寸多行案件编辑器，而不是单行搜索框；编辑器包含新建研究、文档附件、知识库/文件夹选择、链接、Evidence Contract 设置和提交操作。已确认的主色调为 GitHub 方向：

- 冷白、浅灰、墨色、克制蓝和成功绿；
- 保留 Claude 方向的大留白与长期阅读舒适度，不引入装饰性场景元素。

最终实现不复制任何品牌 logo 或具体产品 UI；视觉图只用于色调与密度参考。建议删除生成图中的装饰物和虚构指标，以真实数据驱动页面。

## 9. 部署结构

```text
Internet
   ↓ HTTPS
Caddy
   ├── /        → static Web
   └── /api/*   → FastAPI (single worker)
                         │
                 persistent volume
                 ├── kb.sqlite
                 ├── tasks/
                 └── backups/
```

- Caddy 自动 TLS；
- FastAPI 初期单 worker，匹配 in-memory TaskService 限制；
- 数据 volume 不随容器删除；
- 每日 SQLite snapshot，定期复制到另一存储位置；
- health check 与容器自动重启；
- 日志不记录密码、token、provider key 或完整文档正文。

## 10. 实施阶段与 Gate

### Stage 0 — Composition closure

- [x] 正确装配 FastAPI → TaskService → ResearchService → ResearchEngine；
- [x] HTTP 支持显式 EvidenceRequirement；
- [x] 真实 provider E2E 生成完整 artifacts。

Gate：HTTP 完成一个真实 Research，且 CLI 结果语义不回归。

实际验收（2026-09-15）：默认 `create_app()` 经真实 OpenAI provider 完成 HTTP Research，任务状态为
`running → completed`，Engine status 为 `completed`；report、sources、trace、metrics 四类 artifact
均可读取。本次单内部证据案例为 STOP，Quick/Deep 调用均为 0。新增 Stage 0 interface/integration
测试覆盖完整 HTTP contract、显式 requirement 转发、queued/running/completed/failed、invalid KB、
invalid requirement、artifact 读取和 provider failure 脱敏。网络阻断、forked 的当前完整项目集合为
126 passed；其中包含本轮新增 12 项，原 Research Core 与 CLI 语义测试均通过。

### Stage 1 — Knowledge workspace contract

状态：已完成（2026-09-15）。

- [x] KB 重命名；
- [x] 文档详情/内容预览；
- [x] 指定版本读取；
- [x] DTO 与结构化错误。

Gate：重命名不改变 ID，预览和版本 provenance 正确。

实际验收：`PATCH /api/kbs/{kb_id}` 保持 ID 与创建时间；文档详情返回当前版本、版本数、
4,000 字符解析内容预览与截断标记；指定版本详情返回完整解析文本以及 source URI、content hash、
更新时间、摄取时间和版本状态。HTTP integration 覆盖旧版/当前版内容隔离、superseded/active 状态、
重命名和结构化 404/422；Stage 1 专项 2 passed。
完成 Stage 1 后，网络阻断、forked 的完整项目集合为 128 passed，`git diff --check` 通过。

### Stage 2 — Authentication and backup

状态：已完成（2026-09-15）。

- [x] 单用户 session、CSRF、CLI token；
- [x] SQLite online backup 与完整归档；
- [x] 安全测试。

Gate：未认证访问被拒绝；下载快照通过 integrity check；敏感值不泄露。

实际验收：缺少认证配置时默认 fail closed；浏览器 session cookie 使用 `HttpOnly + Secure +
SameSite=Lax`，修改请求要求 CSRF token，登录失败统一响应并限速。CLI Bearer token 仅在创建时
返回明文，数据库保存 HMAC 摘要，支持列出、创建替代 token 和吊销。数据库下载通过 SQLite
online backup 生成一致性快照并执行 `PRAGMA integrity_check`；完整归档包含 `kb.sqlite`、
`tasks/` 与无敏感值的 `manifest.json`。Stage 2 安全/备份专项 5 passed，完成后网络阻断、
forked 的完整项目集合为 133 passed。

### Stage 3 — Cloud Web

状态：已完成（2026-09-15）。

- [x] 登录、首页、知识库、Research、结果和备份页面；
- [x] 响应式布局与基本无障碍；
- [x] loading/empty/error 状态。

Gate：桌面与手机浏览器完成完整主链路。

实际验收：独立 `web/` 使用 React、TypeScript、Vite、React Router、TanStack Query、Zod、
Lucide 与原生 CSS，实现已确认的 GitHub 风格浅色信息结构。真实浏览器从登录开始，完成新建 KB、
上传并解析原文件、选择知识库、填写 Evidence Contract、提交 Research、读取 report/sources/
trace/metrics、生成 SQLite 快照与完整归档，以及创建 CLI token；请求经过真实 FastAPI、
`TaskService`、`ResearchService` 和 ResearchEngine interface，浏览器验收仅在 Engine interface
注入确定性 provider fixture。桌面 1440×1000 与手机 390×844 均通过布局和可访问名称检查，
生产构建通过。文件夹字段首版只决定附件上传的 `logical_path`，Research 仍按整个 KB 检索，
页面对此限制做了明确说明，没有伪造文件夹过滤能力。

### Stage 4 — Local Control Web

- [x] loopback companion；
- [x] 一键扫描、ingest、push 与备份下载；
- [x] allowed-root/path traversal 防护。

Gate：本地目录推送后，云端同一 `kb_id` 立即出现正确文档版本。

实际验收：新增 `deepresearch_kb local-web` loopback-only companion，页面显示允许目录、云端
authoritative store 和 token 配置状态，支持扫描支持格式、可选本地 `ingest-dir`、认证 `push-dir`
和云端 SQLite 快照下载。目录解析拒绝绝对路径、`..` 穿越、外部 symlink 和非目录；写请求需要
本地 control token；云端错误统一映射为结构化错误。`push-dir` 通过 multipart 上传原文件与
`logical_path`，返回 imported/unchanged/failed 汇总；同一字节幂等，变更字节生成新版本。专项
测试 5 passed；Playwright 桌面与 390×844 移动端浏览器验收完成扫描 → push → 云端版本反查 →
backup 下载，SQLite `PRAGMA integrity_check` 通过。CLI `push-dir` 现在读取 `DRKB_CLI_TOKEN`，
不再发送未认证请求。

### Stage 5 — Deployment

- Docker/Caddy；
- volume、TLS、域名、健康检查和备份计划；
- 一次跨设备验收。

Gate：手机或另一台电脑登录后可查看 KB、发起 Research、取得结果并下载备份。

## 11. 测试范围

- service/interface tests：重命名、预览、版本、requirements、backup；
- HTTP integration：auth、CSRF、上传、任务轮询、artifact、下载；
- browser E2E：登录 → 上传 → Research → report/source/trace → backup；
- local companion：allowed root、路径穿越、push 幂等与失败汇总；
- deployment smoke：HTTPS、持久化、容器重启后 KB 保留；
- 原有 111 项 Research Core 回归继续通过。

## 12. 明确不做

- 双主 SQLite 或自动双向数据库同步；
- 浏览器上传 `.db` 并直接覆盖线上数据库；
- PostgreSQL、Redis、Celery、Kafka 或分布式 executor；
- Multi-Agent、GraphRAG、新 Research algorithm 或扩大 Phase 4.5 benchmark；
- 复杂多租户、组织权限和公开注册；
- 大型 upstream frontend 重构。

## 13. 开发完成后的主验收链路

```text
登录
→ 新建并重命名知识库
→ 拖拽上传文件
→ 查看解析内容与版本 provenance
→ 发起真实 Research
→ 观察 queued/running/completed
→ 查看 report/sources/trace/metrics
→ 本地 Control Web 一键 push 新内容
→ 云端看到同一文档的新版本
→ 下载一致性 SQLite 备份
→ 在另一台设备登录复核
```

部署所需的服务器、域名、反向代理和访问方式信息，在 Stage 5 开始前收集。
