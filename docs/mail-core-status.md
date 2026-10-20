# mail-core 状态 — 仅剩需用户介入的项

> 更新日期：2026-10-21（Asia/Shanghai）  
> 规格：[`mail-core-architecture.md`](./mail-core-architecture.md)  
> 运行 / 切换 / 桌面：[`../mail_core/README.md`](../mail_core/README.md) · [`mail-core-cutover.md`](./mail-core-cutover.md) · [`mail-core-desktop.md`](./mail-core-desktop.md)  
> CI 模板（仓库内）：[`ci/mail-core.workflow.yml`](./ci/mail-core.workflow.yml)

代码侧 mail-core 闭环（模型、同步、remote_operations 读/旗标写回、inbox/detail API、前端乐观 POST、SSE 收件箱失效、Linux PG vendor/pack scaffold、备份 drill、chaos lease）已在仓库完成并推送。  
**下列三项无法由代理单独完成，需要你本人操作或授权。** 除此以外本文件不再罗列已完成项。

---

## 1. GitHub `workflow` scope（才能写入 `.github/workflows`）

当前推送 token **没有** `workflow` scope，因此正式 workflow 只能以模板形式留在 `docs/ci/mail-core.workflow.yml`，无法落到 `.github/workflows/`。

**你需要：**

1. 为用于推送的 PAT / GitHub App 勾选 **`workflow`**（classic PAT）或等价权限。  
2. 把 `docs/ci/mail-core.workflow.yml` 拷到 `.github/workflows/mail-core.yml`（或按需改名）并推送。  
3. 在仓库 Secrets 中按该 workflow 注释补齐所需变量（测试库 URL 等；**不要**把生产 OAuth 密钥写进日志）。

未完成前：本地继续用 `scripts/run-mail-core-tests.sh` 等脚本跑测。

---

## 2. 真实云 OAuth 密钥与租户（可选，仅当你要联真机）

仓库**刻意不做** live 云 OAuth。Gmail / Microsoft Graph 的 refresh + Bearer 传输与写回 mock 已齐；要连真实租户还需你提供：

| 用途 | 你提供 |
|---|---|
| Google | OAuth client id/secret、refresh token 或授权码流程可用的账号 |
| Microsoft | Azure 应用 client id/secret、租户、授权账号 |
| 运行时 | 写入本地/桌面密钥库或约定的 env（**勿**提交进 git） |

没有这些密钥时：继续用 Memory / Dovecot fixture / transport mocks。代理不会代你申请或填入 live secrets。

---

## 3. 公证 / 签名的 macOS 与 Windows 安装包

Linux：`npm run pack:linux` + 可选 vendor `pgsql` 脚手架已可用（CI soft-ok）。  
**macOS 公证（notarize）与 Windows 代码签名**需要你的开发者账号与证书，代理无法代替：

| 平台 | 你需要 |
|---|---|
| macOS | Apple Developer 账号、Developer ID Application 证书、App Store Connect API / notary 凭据；在 CI 或本机跑 `notarize` |
| Windows | 代码签名证书（EV 或标准）及签注流水线 |
| 发布 | 决定是否把签名步骤写进正式 workflow（同样依赖上面的 `workflow` scope） |

未完成前：可本地/无签名目录产物做功能验证，不能当作正式分发安装包。

---

## 明确不在「等用户」清单里的事

- 发信、联系人、系统推送、公网裸暴露 — 规格 §17 范围内**仍不做**。  
- 代理侧不会替你跑 live OAuth、不会伪造公证包、不会在无 `workflow` scope 下强推 `.github/workflows`。

有上述三项任一就绪时，再说一声即可继续对接（例如启用正式 CI、接入真租户、或签注发行）。
