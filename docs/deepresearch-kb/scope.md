# 当前切片：持久化 metadata + 统一 ingest

以根目录 PROJECT_CHARTER.md 为准；不改 upstream core，不启动
backend/frontend/multi_agents/deep_agents，不新增空 research/planner 模块。

## 第 4、5 步的具体契约

4. `KnowledgeStore.ingest(kb_id, file_path, logical_path=..., ...)` 是单文件统一入口。
   Local Import 直接传文件；未来 Web Upload 将文件落盘后调用同一入口。
   默认解析 Adapter 复用 `DocumentLoader([file_path]).load()`，不重写解析器。
   本次没有实现上传 HTTP 路由、URL 下载、目录批量扫描。
5. 保留 KB ID、document ID、version、updated_at、status，以及：

| 字段 | 定义 |
| --- | --- |
| source_type | ingest 使用 `local_import` 或 `web_upload`；研究证据另用 `external_web` 表示外部互联网来源 |
| source_uri | 来源标识；本地默认原文件 file URI，上传必须由调用者传稳定标识，不用临时文件路径 |
| logical_path | KB 内 POSIX 相对路径，例如 `architecture/current.md`；与 KB ID 一起确定文档身份 |
| content_hash | 原始文件字节的 SHA-256，不是解析文本 hash，也不是文档 ID |

上传与本地导入指定相同 KB 和 logical_path 时更新同一文档；不同目录下同名文件不合并。
重复当前内容返回原版本，包括原 provenance，不视为一次新的导入事件。
内容变化生成递增版本并将旧版本标记 superseded；回到历史内容仍生成新版本。
updated_at 是调用者提供的带时区来源时间；未提供时本地使用 mtime，上传使用接收时间。
ingested_at 单独记录入库时间。版本号反映导入顺序，不代表来源事实的新旧或权威性。

SQLite 保存原始字节快照、解析结果以及 metadata；解析前 staging 快照确保 hash 与解析输入一致，
临时文件自动清理。小型语料阶段同步文件/SQLite 操作可接受，未声称适合大文件或高并发服务器。
每次写入是事务，失败不覆盖已有版本。原始 parser 返回字段保存在 pages 中；
upstream 已丢弃的页码等信息不能凭空恢复，尚未建立页级 citation/Chunk/vector index。

## 使用（需在已有 upstream 依赖环境中运行默认解析器）

```python
from deepresearch_kb.knowledge import KnowledgeStore

store = KnowledgeStore("data/kb.sqlite")
kb = store.create_knowledge_base("项目资料")
# 在 async 函数中：
version = await store.ingest(
    kb.id, "/path/to/architecture.md", logical_path="architecture/current.md",
)
versions = store.list_versions(kb.id, "architecture/current.md")
```

## 验证与剩余开发顺序

离线契约测试使用临时 SQLite 和 fake parser：

```sh
python3 -B -m unittest discover -s tests/deepresearch_kb -p 'test_knowledge.py' -v
```

真实 TXT DocumentLoader 冒烟验证已通过，独立 CLI 已加入（见根目录 README）。
完整项目测试：`GPTR_BLOCK_NETWORK=1 .venv/bin/python -m pytest tests/deepresearch_kb -q`。
### 阶段进度记录

- Phase 1.1（已完成）：定义 KB/document/version 元数据和四个 provenance 字段；8 项离线契约测试。
- Phase 1.2（已完成）：统一 `KnowledgeStore.ingest()`；真实 TXT parser 冒烟、CLI workflow；13 项测试通过。
- Phase 1.3（已完成）：在 SQLite 持久化 `chunk`（document/version/ordinal/text lineage），加入确定性的 lexical `retrieve()`；
  active version filtering、KB scope 和版本替换测试已覆盖。
- Phase 1.4（已完成）：接入 SQLite FTS5 持久化检索 Adapter；进程重启后索引仍可用，
  返回仍统一为 Evidence。它是词法检索，不是向量语义检索；未来 LangChain vector index 可替换该 Adapter。
- Phase 1.5（已完成）：新增可选 `LangChainVectorIndex` Adapter。它只适配调用者注入的
  `similarity_search()`，规范化 metadata 为 Evidence，并支持 KB 过滤；不创建、不持久化外部向量库。
- Phase 1.6（已完成）：新增 `chunk_documents()` 与 `LangChainVectorIndexBuilder`，将 active chunks
  以完整 KB/document/version/source metadata 导入调用者提供的 vector store；导入数量和 lineage 已测试。
- Phase 1.7（已完成）：新增显式 `ResearchOrchestrator` 与 `UpstreamExternalResearch` Adapter；
  `internal`、`external`、`hybrid` 三路统一返回 Evidence，Hybrid 固定 internal-first。
- Phase 1.8（已完成）：新增 `render_evidence_context()`，供 upstream synthesis 使用；
  渲染结果显式区分 Internal/External Source，并保留 source URI、logical path、version。
- Phase 1.9（已完成）：新增 `ResearchOrchestrator.write_report()` 薄 Adapter，将统一 evidence context
  传入 upstream `write_report(ext_context=...)`；不复制 prompt，不改 upstream report generator。
- Phase 1.10（已完成）：新增完全离线 `deepresearch_kb.demo`，演示真实 KB ingest、Hybrid evidence
  收集和 report delegation；使用 fake external/reporter，不产生 API 成本。

接下来：为 External/Hybrid 研究新增独立 Adapter（仍不修改 GPTResearcher 主流程）→
固定 corpus 对照 → 显式 External/Hybrid 调用 upstream。自动 source planning、充分性判断、
自适应升级和上传界面均未实现。此切片只证明持久化/版本身份契约，不证明研究质量提升。
