# p005 Worker handlers 中局部导入 Account 导致同作用域前序访问报 UnboundLocalError

- 现象：后台 Worker 处理任何账号同步任务（`sync_account_folders` / `sync_folder_metadata` / `sync_folder_delta` / `reconcile_folder`）时，均报错崩溃：`UnboundLocalError: cannot access local variable 'Account' where it is not associated with a value`，导致所有账号的邮件同步完全停滞。
- 影响：所有新增和存量邮箱账号无法拉取/同步文件夹及新邮件，邮件列表无法接收新邮件。
- 根因：`src/mail_core/worker/handlers.py` 在模块顶部第 13 行已导入 `Account`，但在 `_handle_job_impl` 函数末尾的异常处理分支第 186 行又执行了 `from mail_core.mail.storage.models import Account`。依据 Python 变量作用域规则，函数体内部任意位置存在导入或赋值会导致该变量在整个函数作用域内被判定为局部变量；当第 61 行先执行 `acc = session.get(Account, account_id)` 时，局部变量 `Account` 尚未绑定，触发 `UnboundLocalError`。已扫无同类。
- 测试缺口：现有单元测试未能完整覆盖 Worker 进程中真实调用 `_handle_job_impl` 完整执行流（多使用 mock 或直接调用 engine 函数）。需在 Worker 集成测试中补测从任务队列派发到执行的端到端用例。
- 线索：部署后添加 IMAP 账号触发同步，Worker 日志报错 `job ... (sync_account_folders) failed: UnboundLocalError: cannot access local variable 'Account' where it is not associated with a value`。
- 处理：fix/p005
