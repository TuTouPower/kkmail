> [!NOTE]
> **SUPERSEDED / HISTORICAL REPORT**
> 本报告属于历史审查归档，报告中所列缺陷已在后续版本（截至 da57df7）彻底修复并闭环。

# 只读验证记录

- 时间：2026-10-21T04:11:23+08:00
- 被审 SHA：daca631aec54c30ce02cdb5e6499ae196dc3a72d。
- 所有探针只在内存执行，未启动服务、连接数据库、使用真实凭据、修改源码或运行完整 test/lint/build。

|检查|方法|结果与限制|
|---|---|---|
|SPA 根目录逃逸|AST 提取原 spa_fallback，移除装饰器，FileResponse 用返回 Path 的桩替代，\_DIST 指向已存在 frontend/dist，参数 unquote('%2e%2e/package.json')|原函数返回 frontend/package.json，确实越出 dist。未经过真实 ASGI/反代 HTTP；当前 Python 缺 fastapi/httpx。|
|中文下载响应头|runpy 读取原 http_headers.py，content_disposition_attachment('报告.pdf') 后 encode('latin-1')|UnicodeEncodeError。Starlette latin-1响应头编码行为另由视角2核对。|
|IMAP 缺省 TLS|ssl.\_create_stdlib_context()，并核对 imaplib.IMAP4_SSL 构造分支|verify_mode=0、check_hostname=False。未进行网络 MITM 或读取任何账户密码。|
|CSRF 预取超时|内存转译原 client.ts，只替换 apiBaseUrl 导入与 fetch 边界；postJson 指定 timeoutMs=5，fetch永不resolve，30ms后检查|仍pending，只有/api/auth/me调用，证明CSRF阶段不受请求timeout覆盖；未发网络请求。|
|连续拖列宽|使用现有 TypeScript transpileModule 在内存转译原 ColumnResize；仅 stub useCallback/useRef/window；TypeScript AST 提取原 App 的 onDrag回调，不镜像实现|宽度260、pointerX依次100/120/140，实际宽度280/280，应280/300；捕获陈旧闭包。未运行整套前端测试或DOM交互。|
|未分组账户可见性|提取并执行原 Sidebar grouped 表达式；一个 group、一个 group_id=null账户|总账户1，最终group members数0；未分组账户丢失。|
|生产主链可达性|rg 所有 MessageBody/Attachment 构造以及 ARCHIVE_MIME_BATCH enqueue|正文/附件只在测试构造；归档任务只有自续排没有首次排队。见视角2/3详细调用链。|
|仓库公开状态|gh repo view TuTouPower/kkmail --json isPrivate --jq .isPrivate|false；查询只读。|
|审阅前工作区|git status --short / git diff --stat origin/main|tracked diff为空，既有未跟踪review_20261021_034329完整保留。|

## 未运行验证

- pytest / DB integration：未执行；当前Python无fastapi/sqlalchemy/pytest/httpx，没有经确认的一次性DB，本审阅不安装依赖或启动数据库。
- lint / tsc / vitest / build / Electron suite：未执行。skill要求对此类validation有明确授权；当前按只读审阅做静态与无副作用探针，不声称测试通过。
- 外部协议：视角3采用官方provider文档与当前源码交叉核对；未调用真实Gmail/Graph/IMAP账户。
