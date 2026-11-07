# bundle_followup_q_evo_04_archive_pii_governance

## Summary

经核查 CLAUDE.md、DOCUMENTATION_STANDARD.md 与既往 review 裁决历史，确立明确结论：安全与隐私合规绝对优先于 archive「只准新增」的格式约定，必须执行就地脱敏并建立自动化门禁：

1. 既往裁决判例事实：在 docs/reviews/review_20261027_021416/review_intensive.md:11 中已有明确权威裁决——「archive 只准新增的约束与隐私修订冲突时以隐私优先、留勘误注记」；并在 adoption_decision.md A294/A383 中采纳对敏感标识执行文档级符号化替换、彻底阻断在公开仓中持续分发。
2. 规范位阶事实：DOCUMENTATION_STANDARD.md §6 严格要求「公开文档、日志和证据默认符号化或脱敏，防止未经授权的凭据或路径泄漏」，§2.2 明确修正须用勘误或追加说明。AGENTS.md 中对 docs/archive/「日常只追加」的约束属于文档生命周期状态管理，当其与公开仓开发者隐私、用户真实邮箱（PII）及宿主机安全防护发生冲突时，安全与隐私治理具有最高位阶。
3. 具体处置方案：
    a. 破例就地脱敏：对 docs/archive/pending/p060_gmail_virtual_folder_not_selectable.md:3 泄露的真实邮箱 xiaoxiaoguang2000@gmail.com 替换为 RFC 2606 保留域（user@example.com），对 p027 残留口令长度特征、t075/t061 等 review_code.md 残留的 /Users/karson/... 等宿主机绝对路径执行就地替换，并在文末追加简明勘误注记（Errata: PII/path redacted for public repo compliance）；
    b. 上线自动化门禁：在 .repo_template/hooks/pre-commit 中植入正则阻断，拦截非 RFC 2606 邮箱、绝对路径模式及已知凭据特征，从根源杜绝新 task 归档时敏感信息反复泄漏。
4. 结论：确认为 confirmed，采纳选项 A（脱敏破例就地修复 + 增加自动化门禁）。

## Findings

No findings.

## evidence

```json
[
  "docs/reviews/review_20261027_021416/review_intensive.md:11-12",
  "docs/reviews/review_20261027_021416/adoption_decision.md:3085-3095",
  "docs/reviews/review_20261027_021416/bundle_cross_validation.md:32",
  "coding_agent/docs/DOCUMENTATION_STANDARD.md:33-41",
  "coding_agent/docs/DOCUMENTATION_STANDARD.md:157-158",
  "docs/archive/pending/p060_gmail_virtual_folder_not_selectable.md:3",
  "docs/archive/tasks/t075/review_code.md:6"
]
```

## result

```json
"confirmed"
```
