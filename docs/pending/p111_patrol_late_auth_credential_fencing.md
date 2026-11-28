---
pid: "p111"
slug: "patrol_late_auth_credential_fencing"
status: "todo"
---
# p111 裁决巡检晚到 AUTH 结算的凭据失效副作用是否按租约世代 fencing

- 来源：t097 第 2 轮复审 minor finding t097_code_f003（2026-11-29）。t097 已把巡检冷却写入按租约世代 fencing（过期持有者的晚到失败不得覆盖/复活新世代结算），但 `_settle_account_failure` 中 AUTH 域的凭据失效副作用（`mark_credential_invalid`，同时停用同步）不看 fencing 结果：过期持有者的一次晚到 AUTH 失败仍会使凭据失效。
- 内容：裁决该副作用的世代语义——(a) 维持现状：永久认证失败一经任一巡检观测即失效，与 t090「任何来源的永久认证失败走凭据状态」及 AC-002 无世代限定的表述自洽，凭据确已损坏时世代无关；或 (b) 改为按世代 fencing：只有冷却结算实际落地的结算才连带失效凭据，晚到 AUTH 只记本目录探测失败。若裁决为 (b)，需同步补 AUTH 域晚到交错用例（现 t097 晚到交错用例故障域均为 TRANSPORT）。本条目只登记待裁决语义，不预设结论；t097 复审已判定该项在 AC-003 字面范围外、minor 不阻断。
- 处理：未开
