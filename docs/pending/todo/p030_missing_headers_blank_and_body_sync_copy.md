# p030 缺失发件人与收件人信息直接显示空白及正文未在同步队列时移除内容为空描述

- 来源：用户提出
- 内容：
    1. 发件人与收件人缺失信息统一留白：
        - 发件人姓名（`src/frontend/src/lib/displayName.ts` 中的 `displayName`，影响阅读器发件人 `MR06` 与列表发件人 `ML09`）：若邮件未提供发件人或发件人为空，直接显示空白，不再兜底显示“未知”。
        - 收件人信息（`src/frontend/src/components/MessageReader.tsx` 中的 `MR07`）：若 `detail.to` 未提供或为空，直接显示空白，不再显示“未提供”（当前为 `detail.to || '未提供'`）。
        - 梳理发件人地址行（`MessageReader.tsx:178-180`）在完全缺失发件人邮箱时的展示规范，避免残留冒号或悬空标签。
    2. 正文空占位提示文案优化：
        - 阅读器正文未就绪且未进入同步队列时的占位提示（`src/frontend/src/components/MessageReader.tsx:273-274`）：当前文案为“邮件正文尚未完成同步或内容为空 / 该邮件没有正文内容或内容为空。”，改为直接明确提示正文尚未完成同步，彻底移除“或内容为空”相关模糊描述。
    3. 测试用例同步更新：
        - 更新 `displayName.test.ts` 与 `MessageReader.test.tsx` 中针对 `收件人：未提供` 和发件人 `未知` 的既有断言。
- 处理：未开
