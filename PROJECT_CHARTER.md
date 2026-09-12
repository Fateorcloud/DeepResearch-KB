# DeepResearch-KB Project Charter

> Project: DeepResearch-KB｜知识增强深度研究系统
>
> Status: Project-level source of truth
>
> This document defines the product goal, contribution boundary, architecture direction,
> evaluation principles, and development priorities of DeepResearch-KB.
>
> Any substantial implementation decision that conflicts with this document must first
> explain the conflict and update the corresponding design decision explicitly.
>
> The upstream GPT Researcher source code is authoritative for what GPT Researcher
> currently implements. This document is authoritative for what DeepResearch-KB is
> intended to become.

---

## 1. 项目定位

DeepResearch-KB 是基于 GPT Researcher 二次开发的知识增强深度研究系统。

项目面向需要同时依赖：

- 已有私有知识；
- 外部实时信息；
- 多步骤研究与信息综合；

的复杂研究任务。

典型场景包括技术调研、方案预研、开源项目分析、技术选型、文献研究和竞品调研。

DeepResearch-KB 的核心不是“给 Deep Research 加一个知识库”，也不是“做一个更复杂的 RAG”。

核心目标是：

> 让 Research Agent 在研究过程中能够理解、选择和组合已有知识与外部最新信息，并根据当前证据决定下一步应该查询知识库、搜索互联网、继续 Deep Research，还是结束研究。

---

## 2. 为什么需要 DeepResearch-KB

现有 Deep Research 系统擅长：

Web Search → Source Gathering → Research → Synthesis → Report

但对于真实研究任务，它通常缺少用户已有的长期知识背景。

例如进行技术方案调研时，互联网可以告诉系统：

- 某框架当前支持哪些能力；
- 最新版本发生了什么变化；
- GitHub、官方文档和社区如何评价它。

但互联网无法天然知道：

- 当前项目已经采用什么架构；
- 历史方案为什么这样设计；
- 曾经出现过哪些工程问题；
- 团队已有怎样的技术约束；
- 内部文档中已经得到过什么结论。

传统知识库正好相反。

它能够回答“我们已经知道什么”，但通常不擅长主动发现：

- 还缺少什么信息；
- 哪些信息已经过时；
- 是否应该查询外部来源；
- 应该搜索到什么深度；
- 如何把内部事实和外部事实组织成完整研究结论。

因此 DeepResearch-KB 研究的是：

> Knowledge Base 与 Deep Research 如何真正形成统一研究流程，而不是作为两个独立工具简单拼接。

---

## 3. 产品原则

DeepResearch-KB 首先是 Research System，其次才是 Knowledge Base Application。

核心关系必须始终保持：

Knowledge Base → 为 Research 提供已有上下文

而不是：

Research → 成为知识库问答系统的附加功能

项目不能退化为：

“上传 PDF → Embedding → Vector DB → Chat”

也不能退化为：

“GPT Researcher + 一个 search_kb Tool”

真正需要解决的是 Research Orchestration：

用户的问题需要哪些信息？
哪些信息应该来自内部知识？
哪些应该来自外部世界？
什么时候已有证据已经足够？
什么时候应该继续搜索？
内部与外部信息冲突时应该如何处理？

这些决策才是 DeepResearch-KB 的核心。

---

## 4. 上游能力与个人贡献边界

GPT Researcher 已经具有较成熟的 Deep Research 基础能力。

当前上游已经包含 Web Research、Local Documents、Hybrid Research、
LangChain Documents / Vector Store、文档解析、Source/Citation、
Quick Search / Deep Research 以及 MCP 等能力。

因此以下内容不能作为 DeepResearch-KB 的个人创新：

“实现本地文档读取”
“接入向量数据库”
“实现 Hybrid Search”
“加入 MCP”
“实现 Deep Research”
“增加 Fact Checker”

DeepResearch-KB 应尽可能复用这些成熟能力。

个人贡献应集中在上游能力之间尚未形成完整产品闭环的位置：

Knowledge Base lifecycle
        ↓
Knowledge metadata / version governance
        ↓
Research-level source planning
        ↓
Internal / External evidence integration
        ↓
Evidence sufficiency judgment
        ↓
Adaptive research execution
        ↓
Unified evaluation

原则：

Reuse upstream capabilities.
Own the orchestration and the missing engineering layer.

---

## 5. 目标架构

                    Web UI
                       │
                       │
REST API ───── DeepResearch-KB Core ───── MCP Adapter
                       │
               Research Orchestrator
                       │
          ┌────────────┴────────────┐
          │                         │
   Knowledge Service         External Research
          │                         │
   KB / Documents            Quick Search
   Metadata                   Deep Research
   Retrieval                  Web / GitHub / Docs
          │                         │
          └────────────┬────────────┘
                       │
                Evidence Context
                       │
               Research Synthesis
                       │
              Report / Sources
              Trace / Metrics

Web、REST API、MCP 都只是接入方式。

Research Core 必须独立于具体入口存在。

---

## 6. 核心研究流程

目标工作流：

User Research Task
        ↓
Research Planning
        ↓
Sub-question Decomposition
        ↓
Source Requirement Planning
        ↓
┌──────────────┬──────────────┐
│ Internal KB  │ External Web │
└──────────────┴──────────────┘
        ↓
Evidence Collection
        ↓
Evidence Sufficiency / Conflict Check
        ↓
Need More Research?
   │              │
   No             Yes
   │              ↓
   │       Quick / Deep Research
   │              │
   └───────←──────┘
        ↓
Synthesis
        ↓
Report + Citation + Trace

关键点：

Research Agent 不应该默认认为“搜索越多越好”。

搜索行为应该由研究任务和当前证据状态驱动。

---

## 7. 开发阶段

### Phase 0 — Upstream Baseline

第一阶段不得直接大规模修改代码。

首先完整理解并冻结 GPT Researcher baseline：

GPT Researcher 当前如何完成 Web / Local / Hybrid research；
DocumentLoader 如何工作；
Vector Store 如何接入；
Context 如何组织；
Citation 如何产生；
Quick Search 与 Deep Research 如何调用；
成本和 Trace 如何记录；
现有 Benchmark 如何运行。

必须明确：

Upstream already has
Reuse directly
Need extension
Need new implementation

四类边界。

---

### Phase 1 — Persistent Knowledge Base

目标不是重新实现 Local Documents。

目标是把“一次性的本地文档来源”升级为可管理、可查询、可追踪的知识层。

至少形成稳定实体：

knowledge_base
document
document_version
chunk
source metadata

核心 metadata 至少考虑：

knowledge_base_id
document_id
version
source
updated_at
status

研究任务可以明确选择一个或多个 Knowledge Base。

---

### Phase 2 — Knowledge-enhanced Research

这是项目最核心阶段。

Research Planner 不再只有“研究什么”，还需要判断：

这个子问题需要 Internal Knowledge？
External Knowledge？
还是两者都需要？

形成：

Internal-only
External-only
Hybrid

三类研究路径。

最终报告必须能区分：

Internal Source
External Source

并能够追溯每个重要结论来源。

---

### Phase 3 — Knowledge Version Governance

真实知识库中可能同时存在：

旧方案
当前方案
会议纪要
历史版本
废弃文档

Semantic Similarity 本身不能判断哪个事实当前有效。

因此需要研究：

version
updated_at
status
source authority

如何参与 Retrieval / Rerank / Evidence Selection。

目标不是简单“给 metadata 加字段”，而是降低：

Stale Knowledge Usage

即旧知识影响当前研究结论的问题。

---

### Phase 4 — Adaptive Research

在知识库加入以后进一步观察：

很多问题已经能由内部证据充分回答，但 Agent 仍可能继续进行昂贵的外部 Deep Research。

因此研究：

Evidence Sufficiency → Research Routing

目标流程：

KB
 ↓
Enough evidence?
 ↓ yes
STOP / Synthesis

 ↓ no

Quick Search
 ↓
Enough evidence?
 ↓ yes
Synthesis

 ↓ no / conflict

Deep Research

这里研究的是：

“什么时候值得继续研究？”

而不是单纯做 Token Limit。

---

### Phase 5 — MCP Integration

MCP 是 Integration Layer，不是项目核心。

DeepResearch-KB 在独立 Agent / Web API 能稳定运行后，再通过 MCP 暴露能力。

预期只提供少量高价值能力：

search_knowledge_base
research
get_research_report
get_research_sources

MCP 的价值是：

让 Claude、Cursor、Coding Agent 或其他 Agent
将 DeepResearch-KB 作为 Research Capability 使用。

不能将“支持 MCP”包装成主要创新点。

---

## 8. Evaluation First

任何优化都必须对应一个可观察问题。

不能先设计功能，再寻找指标证明功能有价值。

建立小型但可控的研究测试集。

初期可以包含：

当前架构文档
历史架构版本
ADR
技术方案
会议纪要
README
技术说明
干扰文档

问题至少覆盖：

Internal-only Question
External-only Question
Hybrid Question
Stale-version Question
Complex Research Question

保留多个系统版本：

Upstream Baseline
KB-only
Hybrid
Hybrid + Version Governance
Final Adaptive Research

重点指标：

Internal Fact Coverage
External Fact Coverage
Research Answer Correctness
Citation Correctness
Stale Knowledge Error Rate
Deep Research Trigger Rate
Tool Calls
Token / Cost
Latency

每一次架构修改都必须回答：

What failed?
Why did it fail?
What changed?
Why this solution?
How was it tested?
What improved?
What remains unsolved?

---

## 9. 项目开发原则

第一，Problem First。

不能因为某项技术热门就加入项目。

LangGraph、MCP、Reranker、Graph RAG、Multi-Agent 等技术只有在解决已观察问题时才允许引入。

第二，Upstream First。

GPT Researcher 已经解决的问题优先复用，不重新实现。

第三，Minimal Core Modification。

尽可能通过独立模块、Adapter、Service 或 Extension Point 扩展，
避免大量侵入修改 upstream core。

第四，Measurable Improvement。

没有 baseline 的“优化”不能进入最终项目亮点。

第五，Failure Matters。

必须保留失败案例和能力边界。

第六，Resume-safe Claims。

README、简历和面试中只能描述真实完成并验证过的工作。

规划中的功能不得写成成果。

---

## 10. 非目标

DeepResearch-KB 当前阶段不以以下内容为目标：

通用企业知识管理平台
复杂 RBAC / IAM
审批工作流
通用 Agent 平台
多人协作系统
复杂前端平台
Graph RAG 展示
Multi-Agent 数量展示
模型训练
大规模 Benchmark 刷榜

这些功能只有在核心研究链稳定后，并存在明确问题驱动时才考虑。

---

## 11. 项目最终需要证明什么

DeepResearch-KB 最终不是证明：

“我会调用 GPT Researcher。”

也不是证明：

“我会做 RAG。”

而是证明：

> 我能够基于一个成熟开源 Agent 系统，识别真实使用场景中的能力缺口，
> 在理解原有架构和复用边界的基础上完成工程扩展，
> 通过失败案例和对照实验持续发现问题、修改系统并验证结果。

最终项目故事应自然形成：

GPT Researcher
      ↓
发现只依赖外部调研缺少已有知识背景
      ↓
Persistent Knowledge Base
      ↓
发现内部和外部信息需要在 Research 层统一组织
      ↓
Knowledge-enhanced Research
      ↓
发现旧版本知识影响结论
      ↓
Version Governance
      ↓
发现很多问题无需完整 Deep Research
      ↓
Adaptive Research
      ↓
形成质量、时效、成本均可验证的 Research System

---

## 12. Definition of Done

项目是否成功，不由功能数量决定。

至少需要形成：

一个稳定可复现的端到端 Research Demo；
一套明确的 upstream baseline；
一个可管理的持久化 Knowledge Base；
Internal / External / Hybrid research；
统一 Source / Citation；
一组真实可复现的失败 Case；
至少两次由失败驱动的系统迭代；
一套可重复运行的 Evaluation；
真实的质量、错误率、Token、Latency 数据；
清晰的 Upstream / Personal Contribution 边界。

只有达到这些条件后，项目才进入 Resume-ready 状态。