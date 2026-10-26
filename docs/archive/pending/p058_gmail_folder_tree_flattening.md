# p058 修复 Gmail 命名空间折叠与系统文件夹扁平化展示及前缀剥离

- 现象：Gmail 邮箱在侧边栏呈现多余的 `[Gmail]` 不可选空折叠容器，将已发送、草稿、废纸篓等系统目录错误包裹在内；且所有邮件、已加星标、重要邮件等直接显示带 `[Gmail]/` 裸路径前缀，图标与排序未对齐标准工作流。
- 影响：前端侧边栏文件夹树（`src/frontend/src/components/Sidebar.tsx`）在所有 Gmail 账号下的层级布局与视觉呈现。
- 根因：Gmail IMAP 将系统文件夹放在 `[Gmail]/` 命名空间下，前端根据 `parent_remote_id` 机械嵌套，未对 `[Gmail]` 虚拟命名空间进行解构与提升；名称格式化函数 `getStandardName` 缺少剥离路径分隔符逻辑，角色映射缺失 `all`、`flagged`、`important`。
- 测试缺口：`Sidebar.test.tsx` 现有文件夹树测试仅验证通用父子目录，缺少 Gmail 专属 `[Gmail]/` 结构提升与系统文件夹平铺断言。
- 线索：`src/frontend/src/components/Sidebar.tsx:getStandardName`, `getFolderIcon`, `ROLE_PRIORITY`, `AccountFolders`。
- 处理：main
