# Intensive Review — 视角5 架构、模块边界与死代码 (Architecture & Maintainability)

## 视角摘要

设计模式与分层边界、全量死代码与死 import、状态订阅粒度、代码异味与架构可维护性。

## Findings

- [High][98] src/mail_core/api/accounts.py:24 — 路由层直接操作 ORM 实体击穿分层架构设计 — `api/accounts.py` 直接导入 ORM 实体 `Account, AccountGroup`，且在路由文件内直接读取数据库字段并手动控制事务，违反了 `src/mail_core/README.md`「api: Routes call the application layer only」与分层架构约定 — 业务逻辑与实体映射全部收拢至 application 层，路由层仅消费 DTO。
- [Medium][99] src/mail_core/backup/package.py:397 — 全量死函数 \_extract_plain_tar 定义但从未被调用 — 第 397 行定义 `def _extract_plain_tar(...)`，全仓检索该符号仅在定义处出现 1 次，无任何调用方 — 删除该死函数。
- [Medium][95] src/mail_core/api/app.py:144 — ready 路由直接穿透至底层数据库连接执行裸 SQL — `ready()` 函数直接从 `mail_core.db.session` 获取底层 connection 并执行 `conn.execute(text("SELECT version_num FROM alembic_version"))`，绕过 storage 封装 — 将健康检查封装至 storage/health 门面函数。
- [Medium][95] src/frontend/src/main.tsx:15 — 根级单个 ErrorBoundary 导致局部渲染异常直接造成整站白屏崩溃 — 全站仅在 `main.tsx` 根部包裹单个 `ErrorBoundary`。若邮件正文特殊字符或异常日期导致 `MessageReader` 抛出错误，整个应用将直接展示全局崩溃页面，阻断用户切换侧边栏或进入设置 — 为 `MessageReader`、`MessageList`、`Sidebar` 及设置弹窗分别提供局部 `ErrorBoundary` 降级渲染。
- [Low][99] src/desktop/main.js:52 — 未使用的解构引用 rotateLogFile — 第 52 行 `const { rotateLogFile, RotatingLogStream } = require('./logRotation')`，`main.js` 后续仅使用 `RotatingLogStream`，从未调用 `rotateLogFile`；且在函数中间突兀 require 破坏规范 — 移除未用引用并将 require 移至文件头部。
- [Low][96] src/mail_core/api/mail.py:23 — 未使用的 import AccountInboxStatsOut — 从 `queries` 导入了 `AccountInboxStatsOut`，但该路由文件仅使用 `AccountFolderStatsOut`，未引用该符号 — 删除死 import。
- [Low][96] src/mail_core/blobs/archive.py:17 — 未使用的 import and\_, or\_, update — 从 `sqlalchemy` 导入了 `and_, or_, update`，文件内部未使用 — 删除死 import。
- [Low][96] src/mail_core/backup/package.py:6 — 未使用的 import io 与加解密辅助函数 — 第 6 行 `import io`，第 19 行从 `crypto` 导入加解密辅助函数，未被引用 — 删除死 import。
- [Low][95] src/mail_core/realtime/dispatcher.py:190 — 全量死方法 run_forever 定义但从未被调用 — 定义了 `def run_forever(self) -> None`，全仓生产代码与测试均未引用 — 删除该死代码。
- [Low][95] src/mail_core/blobs/store.py:119 — 全量死方法 key_version_of 未被使用 — `BlobStore` 中定义了 `def key_version_of(...)`，全仓从未被引用 — 删除或补充测试。
- [Low][95] src/mail_core/api/deps.py:77 — 安全依赖 helper require_auth_no_csrf 未被任何路由使用 — 定义了 `def require_auth_no_csrf(...)`，但当前所有路由均挂载 `require_auth` 或公开，无一使用该 helper — 清理死 helper。
- [Low][95] src/frontend/src/components/SettingsModal.tsx:11 — SettingsPage 未传 selector 导致全量订阅 store 产生冗余重渲染 — `const { theme, setTheme, closeSettings } = useMailStore()` 未传递选择器，导致组件订阅了 store 的所有字段，邮件列表滚动与选中均会引发设置弹窗无效渲染 — 拆分为细粒度 selector。
- [Low][95] src/frontend/src/components/ColumnResize.tsx:12 — 渲染期间直接访问 Ref 破坏 React 幂等性 — oxlint 警告：在组件渲染执行流中直接读取 `ref.current` 导致渲染输出不稳定 — 将 Ref 访问移出 render 流程。
- [Low][92] src/mail_core/db/session.py:57 — 失效 helper session_scope 从未被使用 — 定义了 contextmanager `def session_scope(...)`，但全仓业务代码均重复手写 `with Session() as session:` — 业务代码统一接入或清理该死 helper。
- [Low][90] src/mail_core/blobs/access.py:65 — 数据类死方法 read_all 未被使用 — `AttachmentPayload` 数据类定义了 `def read_all(self) -> bytes`，全仓未被引用 — 建议移除。
