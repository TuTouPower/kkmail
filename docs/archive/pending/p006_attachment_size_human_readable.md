# p006 邮件阅读器附件大小未按可读单位格式化

- 现象：邮件正文下方的附件列表展示附件大小时直接拼接原始字节数加 " B"（例如 1MB 附件显示为 "1048576 B"），缺乏人性化单位格式化。
- 影响：邮件阅读器（MessageReader）界面用户体验，大附件与多附件展示不直观。
- 根因：`src/frontend/src/components/MessageReader.tsx` 第 174 行直接渲染 `{att.size_bytes} B`，未引入字节大小格式化工具函数（如 `formatBytes`：B/KB/MB/GB）。
- 测试缺口：前端单测与 E2E 测试仅断言了附件名称与下载链接存在，未校验文件大小的展示格式。
- 线索：`src/frontend/src/components/MessageReader.tsx:174`
- 处理：main
