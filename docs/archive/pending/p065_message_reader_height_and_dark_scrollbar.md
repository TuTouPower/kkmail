# p065 邮件正文高度受限与深色模式下 iframe 滚动条未适配

- 现象：
    1. 在大屏或高分辨率显示器下，邮件正文区域被限制在一个高度狭小的固定方块（约 420px）内，外部屏幕明明有大量可用垂直空间却无法自适应展开，导致用户必须在正文小窗内反复局部滚动。
    2. 在开启深色模式后，邮件正文 iframe 右侧的垂直滚动条仍然呈现为白色/亮灰色的浅色模式样式，未适配深色主题，强光刺眼且与周围暗色设计系统脱节。
- 影响：
    核心邮件阅读体验（`MessageReader.tsx`）受损。长邮件在桌面端阅读局促狭窄，且深色模式下正文内嵌亮白滚动条严重破坏视觉一致性。
- 根因：
    1. 【高度未自适应可用空间】：`src/frontend/src/components/MessageReader.tsx:519, 532` 中的正文 `iframe` 显式硬编码了 `minHeight: 420`，且父级 `.message-paper` 未使用 Flex 弹性拉伸填满视口可用高度，导致正文框体无法自适应扩展。
    2. 【沙箱 iframe 缺乏 color-scheme 宣告】：`src/frontend/src/lib/mailBody.ts:167-171` 的 `buildMailSrcdoc` 未在生成的 HTML `<head>` 注入 `<meta name="color-scheme" content="dark">`，且未在样式中声明 `:root { color-scheme: dark; }` 或 `scrollbar-color`。由于 iframe 受 `sandbox` 强隔离，浏览器独立渲染其内部滚动条时默认沿用浅色系统控件。
        同类位点清单：
    - `src/frontend/src/components/MessageReader.tsx:512-539` 两处 iframe
    - `src/frontend/src/lib/mailBody.ts:167-171` 的 `buildMailSrcdoc`
- 测试缺口：
    1. `src/frontend/src/lib/mailBody.test.ts` 仅对 filter 字符串与 CSP 标签做断言，未校验深色模式下是否包含 `color-scheme` 元信息及滚动条样式。
    2. jsdom 环境不渲染浏览器原生滚动条与布局视口高度，未能提前捕捉到样式与高度缺失。
- 修复方向：
    1. 在 `buildMailSrcdoc` 中，根据主题动态注入 `<meta name="color-scheme" content="${isDark ? 'dark' : 'light'}">`，并在内联样式中声明 `html { color-scheme: ...; scrollbar-color: var(--line-strong) transparent; }`。
    2. 调整 `.reader-scroll` 与 `.message-paper` 布局，使 iframe 容器利用 Flex 弹性伸缩或动态计算自适应撑满视口剩余高度。
- 线索：
    - 复现方式：在深色模式下打开任意内容超出 500px 的邮件，观察正文右侧滚动条（呈亮白色），并最大化窗口观察正文高度（固定在小窗口内无法自适应利用屏幕高度）。
- 处理：main
