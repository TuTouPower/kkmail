# Task review t042（reviewer_focus: 代码）

- 实际审查基线：`3cedba683fd941565ac42a1a2d38e11a33a8eee3`。
- 审查方式：独立读取当前工作区完整实现、相关测试断言及文档；未修改生产代码，未重跑数据库测试。
- reviewed_at：2026-10-23T19:15:21+08:00
- 流程限制：用户授权直接 main 实施，task front matter 的 diff_anchor 为空；现工具只能在 start worktree 时赋值，因此无法渲染正式 prompt。本报告按 code/shared prompt 规则人工审查，以真实基线计算 reviewed_scope，不伪造 active/done 或工作区身份；不声称通过 task-work 状态门禁。

## Round 1 (2026-10-23T19:15:21+08:00)

reviewed_scope: fdb951103ad06ef5

### Findings

零新增 finding。

### 复核结果

- 先前发现的同页 partial 丢字段已修：apply_delta_page 按响应顺序合并 supplied_fields；旗标补入下一 upsert，尾部旗标独立应用，delete 丢弃此前 patch。未以最后一个 partial snapshot 覆盖整封邮件。
- 完整快照 supplied_fields=None 同样按全部字段合并；未知时间/状态不抹去同页早先明确事实。已核对新增完整快照与 flag 顺序回归。
- Graph 以字段存在性而非字段真假判定内容更新；空主题、空摘要、空地址数组均可应用，遗漏内容字段保留原值。日期和状态未知仍跳过，不破坏本地未收敛意图保护。
- Gmail metadata projection 只将实际返回的 snippet/internalDate 标为已提供；正常 hydration 省略 snippet 不清空已有摘要。headers 投影为请求报头的完整集合，缺失报头保持合法空值语义。
- Gmail list/history 均验证请求 ID、labels、headers；详情异常不再吞掉，不完整数据不返回成功页，因而不会推进后续 checkpoint。

### AC 复验方式

- AC-001：re_verified。核对 Graph supplied_fields 与 metadata.\_META_FIELDS/地址组更新守卫，以及真实 PostgreSQL partial from/subject 保留断言。
- AC-002：re_verified。核对 Graph has_content 的字段存在性分支与显式空值真实持久化断言。
- AC-003：re_verified。核对 Gmail supplied_fields、两个读取路径及无 snippet 的 list/history upsert 持久化断言；无正文生成摘要写回。
- AC-004：re_verified。核对 hydration validation、移除异常降级、no-id/id-only/mismatch/GET failure 用例；返回页之前异常上抛，数据库 checkpoint 无机会接收成功页。
- AC-005：re_verified。核对完整快照合并、同页顺序、metadata 本地状态意图守卫与既有 provider/metadata 测试断言。
- coverage = 5 / 5

### 结论

- 正确性、安全、公开契约、性能、模块职责、异常处理及文档一致性均已扫描；未发现新增阻断。
- 规模与复杂度提示：sync/delta.py 472 行，providers/gmail.py 410 行；apply_delta_page 原有同步状态处理与新增合并逻辑分支较多。保持批量数据库 upsert，没有引入逐条查询；无已验证行为缺陷，不扩大本轮重构范围。
- 验证限制：独立复核实现与测试断言，未重跑数据库/外部邮箱测试；不把实施侧运行结果称为 reviewer 实测。
- 系统性 follow-up：direct-main 与任务工具状态入口不匹配，已向主代理报告；不阻断当前实现正确性。

verdict: PASS
