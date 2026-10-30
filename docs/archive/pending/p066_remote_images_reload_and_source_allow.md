# p066 远程图片放行后未重载、刷新丢失放行状态及缺少按来源允许加载机制

- 现象：
    1. 用户在阅读包含外链图片的 HTML 邮件时，点击「仅此邮件允许加载」按钮后，邮件正文 iframe 未重新加载，图片依然呈占位/碎图状态。
    2. 刷新网页后，先前针对该邮件的放行设置完全失效，页面再次提示「远程图片已拦截（防追踪）。 仅此邮件允许加载」。
    3. 用户切换到其他邮件并放行后，再返回原邮件，原邮件的放行状态同样丢失。
    4. 当前系统完全缺乏按发件人来源或域名全局/批量放行远程图片的机制。
- 影响：
    1. 用户无法可靠查看邮件中的外链图片，交互操作给用户造成“设置未生效/功能损坏”的不良体验。
    2. 每次刷新页面或切换会话均需重新手动放行，重复操作成本高。
    3. 对于固定订阅、内部通讯或可信发件方，缺乏“总是允许该来源图片”能力，用户体验繁琐。
- 根因：
    1. 主点根因（未重新加载）：`src/frontend/src/components/MessageReader.tsx:517, 528` 中 iframe 的 `key` 为 `${currentMailKey}-${resolvedTheme}-original` 或 `${currentMailKey}-${resolvedTheme}-${isDarkInverted ? 'inverted' : 'normal'}`，**未将 `loadRemoteImages` 纳入 key**。状态改变时 React 仅就地修改 `iframe.srcdoc`，未触发 iframe 节点的卸载重建（remount）。在 WebKit/Safari 及部分 Chromium 浏览器场景下，已有 DOM 节点就地更新属性不会重新发起先前被 CSP 阻断的资源请求；必须通过更新 key 强制 remount 生成全新上下文。
    2. 主点根因（状态未持久化与单值覆盖）：`MessageReader.tsx:81-83` 中放行状态采用组件局部 `useState<string | null>(null)` 维护，既未持久化到本地存储（`localStorage`）或状态树（`mailStore`），也未采用集合结构（`Set`）。刷新网页后组件重新挂载，状态重置为 `null`；切换多封邮件放行后，后放行的邮件 key 直接覆盖先前的 key。
    3. 潜在同源关联（`cid:` 协议未映射）：很多邮件正文看似“占位”的图片为邮件内联附件（`cid:...`），kkmail 全栈尚无针对 `cid:` URL 转换为附件预览地址的机制，导致包含 `cid:` 的图片即使放行外链依然无法加载。
    4. 功能缺口（按来源放行）：系统设计期仅在 `MessageReader` 提供单封临时放行，未在数据库或前端存储层设计发件人地址/域名白名单表或偏好设置。
    5. 已确认同类位点：
        - `src/frontend/src/components/MessageReader.tsx:82`：`viewModeOverride`（深色阅读模式原色/智能单信覆盖）同样采用单值标量 `useState<{ key: string; mode: 'smart' | 'original' } | null>(null)`，存在刷新页面即丢失、切换多封邮件互相覆盖的完全同类缺陷。
- 测试缺口：
    1. `src/frontend/src/components/MessageReader.test.tsx:623-647` 仅在 jsdom 环境断言了 `iframe.srcdoc` 字符串包含 `img-src https:`，而 jsdom 并不发起网络请求或校验 iframe remount 行为，造成测试假绿。
    2. 缺乏测试覆盖组件 unmount/remount 后的放行状态持久性、多封邮件切换放行后的集合保留能力，以及 iframe DOM 节点是否真实 remount。
    3. 补测建议：在 `MessageReader.test.tsx` 中增加断言 iframe 节点引用更新（remount 验证）、多邮件切换放行保留与持久化加载测试。
- 线索：
    - `src/frontend/src/components/MessageReader.tsx:81-83, 517, 528`；
    - `.scratch/repro_remote_images_issue.md`；
    - `.scratch/test_remote_images_bugs.test.tsx`。
- 处理：t066
