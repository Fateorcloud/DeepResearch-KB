"""Materialise hand-authored labels using exact sentences from the pinned corpus."""

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from deepresearch_kb.semantic_claims import evidence_sentences
from ..retrieval_v2.fetch_corpus import DEFAULT_CORPUS, MANIFEST, SNAPSHOTS


# path, exact sentence anchor, paraphrase, related-but-absent claim, paraphrase rationale
POSITIVES = [
    ("tutorial/security/oauth2-jwt.md", "我们需要安装 `PyJWT`", "PyJWT 可用来创建并验证 JWT。",
     "PyJWT 默认每小时轮换一次签名密钥。", "生成和校验分别改写为创建和验证；对象仍是 JWT。"),
    ("tutorial/security/oauth2-jwt.md", "pwdlib 是一个用于处理密码哈希", "pwdlib 提供口令散列处理功能。",
     "pwdlib 默认采用 SHA-1 哈希密码。", "密码哈希改写为口令散列，没有增加算法或安全性结论。"),
    ("tutorial/security/oauth2-jwt.md", "JWT 意为", "JWT 是 JSON Web Tokens 的缩写。",
     "JWT 的载荷默认使用 AES 加密。", "意为改写为缩写展开，保留原英文全称。"),
    ("tutorial/sql-databases.md", "为每个请求提供一个新的 `Session`", "每次请求都能通过带 yield 的 FastAPI 依赖得到新数据库会话。",
     "每个 Session 默认采用可串行化事务隔离级别。", "新的 Session 改写为新数据库会话，保留逐请求和 yield 条件。"),
    ("advanced/events.md", "配置**启动**和**关闭**的推荐方法", "建议用应用的 lifespan 设置启动与关闭逻辑。",
     "lifespan 关闭处理的默认超时为三十秒。", "推荐方法改写为建议，保留 lifespan 与两个生命周期阶段。"),
    ("tutorial/body-updates.md", "也就是说，你只需发送想要更新的数据", "局部更新可以只传待改字段，其他数据维持原值。",
     "局部更新发生并发冲突时自动返回 409。", "发送更新数据改写为只传待改字段；保留其余不变。"),
    ("tutorial/query-params-str-validations.md", "但现在把 `Query(max_length=50)`", "这个 Query 校验将文本限制在五十个字符以内。",
     "Query 会自动截断超过长度上限的输入。", "最大长度 50 改写为五十以内，没有推断如何处理超限。"),
    ("advanced/settings.md", "从环境变量读取的任何值都是", "Python 读出的环境变量值一开始都是字符串。",
     "Python 读取环境变量时自动解码 Base64。", "str 改写为字符串；限定读取时而非转换之后。"),
    ("tutorial/response-model.md", "`response_model` 会具有优先级", "同时指定返回注解和响应模型时，FastAPI 优先采用响应模型。",
     "response_model 会自动加密敏感响应字段。", "保留同时声明的条件，将返回类型改写为返回注解。"),
    ("tutorial/security/simple-oauth2.md", "OAuth2 规范要求使用“密码流”", "OAuth2 密码模式要求以表单提交用户名和口令。",
     "OAuth2 密码流会自动把用户名转成小写。", "密码流改写为密码模式，username/password 改写为用户名/口令。"),
    ("tutorial/request-files.md", "`File` 是直接继承自", "File 的直接父类是 Form。",
     "File 会默认拦截所有 exe 扩展名的文件。", "直接继承改写为直接父类，未改变类名。"),
    ("tutorial/testing.md", "要使用 `TestClient`，先要安装", "使用测试客户端前需要装好 httpx。",
     "TestClient 遇到失败请求默认重试三次。", "先要安装改写为使用前装好，依赖名不变。"),
    ("tutorial/middleware.md", "在请求路径上，最外层的中间件先运行", "处理请求时，会先执行最外侧的中间件。",
     "中间件超过十毫秒就会被自动中止。", "保留请求方向和外层先执行的顺序，未推断响应顺序。"),
    ("tutorial/cors.md", "你可以在 **FastAPI** 应用中使用 `CORSMiddleware`", "FastAPI 可通过 CORSMiddleware 设置跨域行为。",
     "CORSMiddleware 自动校验 WebSocket 消息的业务格式。", "在 CORS 文档中配置它改写为设置跨域行为。"),
    ("tutorial/background-tasks.md", "你可以定义在返回响应后运行的后台任务", "可以让后台工作在响应已发回后执行。",
     "后台任务失败后默认会持久化并重试三次。", "保留响应返回后执行这一时序，没有推断可靠性保证。"),
]

# All evidence below is real negative wording, never a synthetic negated document.
NEGATIVES = [
    ("tutorial/path-params.md", "OpenAPI 不支持声明", "OpenAPI 支持声明内部包含路径的路径参数。",
     "原句明确说 OpenAPI 不支持这种声明，与正向要点相反。"),
    ("tutorial/request-files.md", "但不能同时声明希望以 JSON 接收的", "声明 File 和 Form 时可以同时用 Body 接收 JSON。",
     "原句明确否定在这种 multipart 请求中同时接收 JSON Body。"),
    ("advanced/response-directly.md", "**FastAPI** 不会用 Pydantic 模型做任何数据转换", "直接返回 Response 时 FastAPI 会用 Pydantic 转换数据。",
     "原句明确说不会用 Pydantic 做任何数据转换。"),
    ("advanced/response-directly.md", "当你直接返回 `Response` 时", "直接返回 Response 时会自动生成文档。",
     "原句同时否定校验、转换和自动生成文档，要点只取最后一项的反面。"),
    ("tutorial/static-files.md", "主应用的 OpenAPI 和文档不会包含", "主应用的 OpenAPI 文档包含挂载应用的内容。",
     "原句中的不会包含直接否定包含。"),
    ("tutorial/dependencies/index.md", "你不需要直接调用它", "把依赖函数传给 Depends 时需要先加括号直接调用它。",
     "原句明确要求不要在末尾加括号，只传函数。"),
    ("advanced/events.md", "两者不能共用", "lifespan 可以和全部启动关闭事件配置共用。",
     "原句使用要么以及不能共用排除了同时启用。"),
    ("tutorial/query-params-str-validations.md", "不能再给 `Query` 传 `default`", "在 Annotated 中使用 Query 时仍可给 Query 传 default。",
     "原句明确否定再给 Query 传 default，而不是讨论默认值的具体内容。"),
    ("tutorial/body.md", "Swagger UI 的交互式文档不会显示请求体的文档", "使用 GET 时 Swagger UI 会显示请求体文档。",
     "原句对 GET 请求体的文档显示作明确否定。"),
    ("tutorial/testing.md", "注意测试函数是普通的", "这里的测试函数应声明为 async def。",
     "原句要求普通 def 并明确说不是 async def。"),
    ("tutorial/body-updates.md", "不会用模型中的默认值覆盖已存储的值", "这种局部更新会用模型默认值覆盖已存储的值。",
     "原句明确否定用默认值覆盖，且保留局部更新上下文。"),
    ("tutorial/body.md", "但客户端不一定总是要发送", "客户端总是必须发送请求体。",
     "不一定总是及不会发送请求体给出了不发送的情况，否定全称断言。"),
    ("tutorial/query-params.md", "查询参数不是路径的固定内容", "查询参数是路径的固定内容。",
     "原句直接用不是否定路径的固定内容。"),
    ("tutorial/response-model.md", "确保不会把类继承的这些规则用于返回数据的过滤", "FastAPI 会把类继承的类型规则直接用于返回数据过滤。",
     "原句明确保证不会用类继承规则做这种过滤。"),
    ("tutorial/security/simple-oauth2.md", "因此，不能使用 JSON 对象", "这个用户名密码提交流程可以使用 JSON 对象。",
     "原句要求表单 username 和 password 并明确排除 JSON 对象。"),
]


def build(corpus=DEFAULT_CORPUS):
    manifest = json.loads(MANIFEST.read_text())
    cases = []

    def sentence(path, anchor):
        raw = (corpus / "v2" / path).read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        assert digest == manifest["files"]["v2/" + path], path
        sentences = evidence_sentences([SimpleNamespace(chunk_id="e", text=raw.decode())])
        matches = [s["text"] for s in sentences if anchor in s["text"]]
        if len(matches) != 1:
            raise ValueError(f"ambiguous sentence: {path}: {anchor}: {len(matches)}")
        return matches[0], {"path": path, "snapshot": SNAPSHOTS["v2"], "sha256": digest}

    def add(kind, index, claim, text, source, label, rationale):
        cases.append({"id": f"{kind}_{index:02}", "type": kind, "claim": claim,
                      "evidence": text, "label": label, "source": source, "rationale": rationale})

    for index, (path, anchor, paraphrase, absent, rationale) in enumerate(POSITIVES, 1):
        text, source = sentence(path, anchor)
        add("literal", index, text, text, source, "supported", "要点逐字重述证据句；保留全部条件。")
        add("paraphrase", index, paraphrase, text, source, "supported", rationale)
        add("related", index, absent, text, source, "not_found",
            "原句只说明“" + paraphrase + "”；没有说明要点中的额外行为或参数，不能由相关性推断。")
    for index, (path, anchor, claim, rationale) in enumerate(NEGATIVES, 1):
        text, source = sentence(path, anchor)
        add("negation", index, claim, text, source, "contradicted", rationale)
    return {"schema_version": 1, "label_origin": "hand-authored; no LLM labels", "cases": cases}


if __name__ == "__main__":
    target = Path(__file__).with_name("cases.json")
    target.write_text(json.dumps(build(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("wrote 60 labelled examples")
