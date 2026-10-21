# p002 邮件正文未归档或为空时阅读器静默空白无提示

- 现象：在邮件列表中点击一封尚未完成正文归档或正文内容为空的历史邮件时，右侧阅读器未能加载富文本沙箱 iframe，仅静默展示一段简短的纯文本摘要，无任何“正文未下载”或“正文为空”的状态提示与重试引导。
- 影响：用户误以为系统加载失败、邮件内容损坏或出现白屏，无法直观区分该邮件是纯文本、正文尚未同步还是确实内容为空。
- 根因：`MessageReader.tsx` 中 `html` 变量判定依赖 `!!detail?.body && isHtmlBody(detail.body_type)`；当后端返回 `body_type: "empty"` 且 `body: ""` 时，`html` 判定为 `false`，界面回退展示 `selected.body_preview` 并在普通 `div` 中渲染，未渲染沙箱 iframe，且没有对 `body_type === "empty"` 做出显式状态展示。
- 同类位点：附件处于未下载状态或归档暂停状态时的卡片展示。
- 测试缺口：现有单测（如 `test_message_detail_api.py`）手工 seed 了完整的 HTML 正文，未覆盖生产环境中邮件只有元数据、尚未完成 MIME 归档时的空正文边界。应在前端与端到端测试补充未归档邮件展示“正在拉取正文/正文尚未同步”的空态用例。
- 线索：端到端实测读取历史导入邮件《我们希望了解你为何取消 ChatGPT Pro 订阅》时 `hasIframe: false`，接口返回 `body_type: 'empty'`。
- 处理：fix/p001-p004
