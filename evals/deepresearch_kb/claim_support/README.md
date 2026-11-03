# 中文要点支持判断小型评测

2026-11-03 实际运行。结果是这组人工样例上的观察，不能当作通用准确率。

## 数据与拆分

`cases.json` 共 60 条人工标注：原文直述、改写、中文否定、相关但未提及各 15 条。
每条保留原始证据句、要点、三分类标签、标注理由、源文件及 SHA-256。
证据全部来自现有 retrieval_v2 语料的 FastAPI 中文文档，固定提交
`45cb2252c737906f37544f5ba6bee0295fb81468`，许可 MIT；否定句也是真实原句，没有合成反向证据。
`build_cases.py` 可重建样例，运行器会校验源文件字节哈希和证据子串。

按 `int(sha256(id), 16) % 5 < 2` 固定分到 test，其余为 dev，未按评测表现调整 ID。
dev 41 条：直述 11、改写 7、否定 13、相关 10；test 19 条：直述 4、改写 8、否定 2、相关 5。

## 方法与 dev 校准

1. 字面：直接调用产品 `_claim_supported`，含中英文紧邻否定规则；匹配成功为
   `supported`，否则 `not_found`。这个保守基线不输出 `contradicted`。
2. 仅向量阈值：`BAAI/bge-small-zh-v1.5`，fastembed 0.7.3，CPU，中文 query instruction
   与 retrieval_v2 一致；余弦相似度达阈值即预测支持。此方法仅用于暴露相似度的局限，产品不会这样判定。
3. 字面 + 向量候选 + LLM：字面失败后按产品代码切句，取余弦相似度达阈值的前 5 句，
   大模型返回 `supported / contradicted / not_found` 并引用候选句编号。
   格式或编号无效为 `unknown`，支持和矛盾都要求非空有效引用。

阈值只在 dev 上校准：在 0.30–0.95、步长 0.01 的预定网格中，选择使 dev 支持样例候选召回率
至少 95% 的最高阈值，结果为 **0.47**（18/18）。它是候选筛选阈值，不是支持概率。
生产默认写在 `deepresearch_kb.semantic_claims.SemanticConfig`，默认 k=5；
`calibration.json` 留存所有网格结果和 dev ID，`results_dev.json` 留存原始余弦分数。
test 没有参与阈值选择，也未根据其结果重标或修改提示词。

## Test 结果

| 方法 | 改写支持识别率 ↑ | 否定误判支持率 ↓ | 整体三分类准确率 ↑ |
|---|---:|---:|---:|
| 仅字面 | 0/8（0.00%） | 0/2（0.00%） | 9/19（47.37%） |
| 仅向量阈值 | 8/8（100.00%） | 2/2（100.00%） | 13/19（68.42%） |
| 字面 + 向量候选 + LLM | 8/8（100.00%） | 0/2（0.00%） | 18/19（94.74%） |

大模型部分**实际运行**：复用现有 `SMART_LLM`，provider `openai`、model `deepseek-flash`
（现有兼容接口），14 个要点实际进入 LLM 复核，1 个 unknown，按错误计入整体准确率。
其余 4 个字面支持，1 个没有达到候选阈值。未记录密钥、请求头或 provider kwargs。
`results_test.json` 保留每条预测、候选编号、原句、相似度与有效引用。

最终组合方法的唯一错误为 `related_08`：证据说环境变量读取结果为字符串且类型转换、验证需由代码完成；
要点说会自动解码 Base64。人工按“没有说明 Base64 行为”标成 `not_found`，最终复核为
`unknown`，没有有效引用。调用异常和输出校验失败都保守返回 unknown；未保存原始响应，不能进一步区分原因。

初次使用 fastembed 0.9.1 时也是 18/19，但该样例曾被判为 `contradicted`。
干净检出的依赖解析发现 0.9.1 与项目 NumPy 约束冲突，因此固定兼容的 0.7.3 后重跑同一 test；
表中只使用最终版本结果，保留 unknown，没有择优。阈值仍为 dev 校准的 0.47，标注和提示词未改。
这两次复核也说明模型判断会波动，引用有效不能保证推理一定正确。

## 复现

```bash
uv run python -m evals.deepresearch_kb.retrieval_v2.fetch_corpus
uv run python -m evals.deepresearch_kb.claim_support.build_cases
# 如缓存中没有模型，显式预下载；研究请求本身只加载本地模型。
uv run --with fastembed==0.7.3 python -c 'from fastembed import TextEmbedding; from pathlib import Path; TextEmbedding("BAAI/bge-small-zh-v1.5", cache_dir=str(Path.home()/".cache/fastembed"))'
uv run --with fastembed==0.7.3 python -m evals.deepresearch_kb.claim_support.run --split dev --calibrate --llm off
# 确认 dev 选择与 SemanticConfig 一致后，固定配置运行 test。
uv run --with fastembed==0.7.3 python -m evals.deepresearch_kb.claim_support.run --split test
```

运行器加载已有 `.env`，通过项目 Config / GenericLLMProvider 调用大模型；可以用
`--llm off` 只运行前两种。provider 无法初始化时会明确记录 unavailable；调用异常或无效输出
则按 unknown 计错，不重试或丢弃样例。生产可用 `uv sync --extra semantic` 安装可选依赖。
固定 fastembed 0.7.3 与项目现有 NumPy `<2.3` 约束兼容，不改变项目的 Python 版本范围。
缺依赖、缺本地模型或无法初始化 LLM 时记录 `semantic_unavailable`。

## 局限

仅 19 条 test，尤其否定类只有 2 条，比例方差很大；人工单人标注也有判断偏差。
按用户要求按样例 ID 拆分，同一原句的直述、改写、相关要点可能跨 dev/test，因此它不是独立文档泛化评测。
每条只有一个句子，不能证明 k=5 的多句排序效果、跨句推理、多来源约束或冲突消解质量；
这些约束另由假的嵌入和大模型单元测试覆盖。语料只涉及 FastAPI 中文技术文档。
LLM 即使 temperature=0 仍可能波动，且评测依赖本地已有模型服务配置。
字面与纯向量基线只预测支持/未提及，不能正确识别三分类里的矛盾，整体准确率因此受到限制。
没有衡量生成要点的事实正确率、端到端报告质量、延迟、费用或真实生产表现。
