> [!NOTE]
> **SUPERSEDED / HISTORICAL REPORT**
> 本报告属于历史审查归档，报告中所列缺陷已在后续版本（截至 da57df7）彻底修复并闭环。

# intensive-review rubric — kkmail @ 608e284

全库当前态审阅。工作区干净，HEAD = origin/main = `608e284f75f1da1540138728b3bf328b194a9720`。没有 diff 可当范围。当前代码里的问题全部计入。不要因为「以前就这样」丢弃。

上次审阅 `docs/reviews/review_20261021_011116/` 针对 `b295644`（当时仍有 Flask / outlook_web / GitHub CI）。其后提交已删除这些路径并修过一批 High/Medium/Low。禁止抄旧 finding。只报告在当前文件里仍能指到行号的问题。

只读产品代码。只允许写入任务指定的那一个 `bundle_*.md`。

## 项目不变量（违反才是缺陷；符合不要报）

- 单用户。Session / API Key 边界内，知道资源 UUID 即可访问。不要按多租户 IDOR / RLS 报缺陷。见 `Agents.md` 与 `docs/security.md`。
- 产品不含发信、联系人、系统通知、浏览器扩展。不要把「没有这些功能」报成缺口。
- 邮件 HTML 只能经 `frontend/src/lib/mailBody.ts`。禁止 `dangerouslySetInnerHTML`。是否 HTML 只看 `body_type`。
- 消息 ID 是 mail-core UUID；账户 ID 是 UUID，不用邮箱当 ID。
- HTTP 只经 `frontend/src/api/client.ts`。写请求带 `X-CSRF-Token`。
- 路由声明 `response_model`；错误是 `HTTPException` `{"detail": ...}`。路由只调用 `mail_core.mail.application` / `mail_core.accounts`，不直接碰 ORM 或 sync 内部。
- 密钥无默认值、无示例密钥；缺失拒绝启动。凭据只经 `CredentialStore`。日志和 `last_error` 必须经 `mail_core.security.redact`。
- 生成物 `frontend/src/api/generated/schema.ts` 与 `docs/openapi.json` 禁止要求手改。漂移应指向生成源（路由 / schema）和 `scripts/gen-openapi.sh`。
- UI 文案中文。图标按钮要有 `title` 与 `aria-label`。破坏性操作先 `confirmAction`。移动端断点 760px。
- 公开仓库 `https://github.com/TuTouPower/kkmail`（visibility PUBLIC）。隐私与历史泄漏要报，但报告里打码，不要复述完整 token / 密码 / cookie。

## 八个视角（都要扫，禁止只写最有把握的一类）

1. 安全：注入、XSS、CSRF、SSRF、路径遍历、反序列化、认证会话、越权（单用户模型下仍看未认证入口、CSRF、密钥泄漏）、日志泄密、弱加密、调试暴露、依赖与默认凭据。
2. 正确性：空值、类型、缺 await、rejection、竞态、死锁、off-by-one、迭代中修改、溢出、时区、资源泄漏。
3. 契约：optionality、公开 API / 配置键 / schema 不兼容、状态码不一致、缺校验、路由绕过 application 层。
4. 性能：N+1、缺索引、无分页、循环查库、同步 IO 堵异步、无超时、重复渲染、整包引入大库。
5. 架构：重复、错层、循环依赖、死代码、超长函数、同一分支散落多处。规模问题标 Medium/Low，不要标成 High，除非已造成确定 bug。
6. 健壮性：空 catch、吞错、缺超时/重试/幂等、失败不回滚、日志缺上下文或含敏感信息。
7. 测试：核心路径无测试、断言恒真、改断言迁就实现、mock 掉被测逻辑、跳过失败。覆盖缺口除「核心路径无测试 / 验证假行为」外标 Low。关联测试在 `tests/mail_core/`、`frontend/src/**/*.test.ts(x)`、`desktop/`。
8. 文档：三态（当前/过时/未来）混写、未来冒充当前、无证据断言、双权威、README 与实现不一致、会话残留、破坏性命令缺恢复步骤、手改生成物。参考 `/Users/developer/kar/code/my_file/coding_agent/docs/DOCUMENTATION_STANDARD.md`。

## 分级

- Critical：未认证即可造成远程损害、密钥泄漏、数据丢失、正常路径崩溃。
- High：确定能走到的逻辑 bug，或明确的性能/数据正确性陷阱。
- Medium：边界、可维护性、非核心路径缺陷。
- Low：文档、风格、非核心覆盖缺口。
- Info：观察，不含必须修改的缺陷。
- 置信度 0–100。0 假阳性，25 可能，50 真但低频，75 已在代码确认且较容易触发，100 绝对确定。低置信度也要报。
- lint / 格式化 / 未使用 import 这类工具能抓的，标 Info，不要标 High。
- 文件里有 `// @review-ok` 或 `# @review-ok` 的行跳过。

## 输出

文件以 `# Bundle <id>` 开头。

`## Findings` 下每条缺陷独占一行，供 aggregate.py 解析。格式：

`- [Severity][置信度] path:line — 标题 — 证据 — 修复`

- Severity 只能是 `Critical` `High` `Medium` `Low` `Info`
- path 相对仓库根，含扩展名，中间无空格
- line 是起始行号
- 分隔符是 ` — `（空格 + em dash + 空格）
- 一行内写完，不要换行

然后 `## Notes`：每个视角一小节，写扫过什么、没有发现时写「未发现」。Notes 不要再使用上面的列表格式，避免重复计数。

没有缺陷时 Findings 留空，并在 Notes 列出已完整阅读的文件。禁止编造。

## 阅读要求

任务列出的每个文件必须从头读到尾。生成的 JSON / schema 允许按契约抽查（路径、认证、字段 optionality），不要对生成物做风格审阅。CHANGELOG 历史条目只在被 README 或现行文档当成当前事实时才报。
