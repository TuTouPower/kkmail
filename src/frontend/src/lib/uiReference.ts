export interface UiElementMeta {
  id: string
  region: string
  description: string
}

export const UI_ELEMENT_REGISTRY: Record<string, UiElementMeta> = {
  // Login (LG)
  LG01: { id: 'LG01', region: '登录', description: '登录页标题' },
  LG02: { id: 'LG02', region: '登录', description: '密码输入框' },
  LG03: { id: 'LG03', region: '登录', description: '登录提交按钮' },
  LG04: { id: 'LG04', region: '登录', description: '登录错误提示' },

  // Sidebar (SB)
  SB01: { id: 'SB01', region: '侧栏', description: '折叠或关闭侧栏按钮' },
  SB02: { id: 'SB02', region: '侧栏', description: '个人收藏分类标题' },
  SB03: { id: 'SB03', region: '侧栏', description: '所有收件箱分类' },
  SB04: { id: 'SB04', region: '侧栏', description: '所有未读分类' },
  SB05: { id: 'SB05', region: '侧栏', description: '已发邮件分类' },
  SB06: { id: 'SB06', region: '侧栏', description: '草稿箱分类' },
  SB07: { id: 'SB07', region: '侧栏', description: '废纸篓分类' },
  SB08: { id: 'SB08', region: '侧栏', description: '垃圾邮件分类' },
  SB09: { id: 'SB09', region: '侧栏', description: '邮箱账户分组标题' },
  SB10: { id: 'SB10', region: '侧栏', description: '邮箱账户行模板' },
  SB11: { id: 'SB11', region: '侧栏', description: '侧栏底部设置按钮' },

  // Message List (ML)
  ML01: { id: 'ML01', region: '邮件列表', description: '侧栏展开按钮' },
  ML02: { id: 'ML02', region: '邮件列表', description: '列表视图标题' },
  ML03: { id: 'ML03', region: '邮件列表', description: '刷新并同步按钮' },
  ML04: { id: 'ML04', region: '邮件列表', description: '搜索输入框' },
  ML05: { id: 'ML05', region: '邮件列表', description: '清除搜索按钮' },
  ML06: { id: 'ML06', region: '邮件列表', description: '邮件排序切换按钮' },
  ML07: { id: 'ML07', region: '邮件列表', description: '标记全部已读按钮' },
  ML08: { id: 'ML08', region: '邮件列表', description: '邮件列表行模板' },
  ML09: { id: 'ML09', region: '邮件列表', description: '邮件发件人' },
  ML10: { id: 'ML10', region: '邮件列表', description: '邮件主题' },
  ML11: { id: 'ML11', region: '邮件列表', description: '邮件接收日期' },
  ML12: { id: 'ML12', region: '邮件列表', description: '邮件正文摘要' },
  ML13: { id: 'ML13', region: '邮件列表', description: '列表空状态' },
  ML14: { id: 'ML14', region: '邮件列表', description: '列表加载更多按钮' },

  // Message Reader (MR)
  MR01: { id: 'MR01', region: '邮件详情', description: '阅读器顶部工具栏' },
  MR02: { id: 'MR02', region: '邮件详情', description: '已读/未读切换按钮' },
  MR03: { id: 'MR03', region: '邮件详情', description: '旗标切换按钮' },
  MR04: { id: 'MR04', region: '邮件详情', description: '删除至废纸篓按钮' },
  MR05: { id: 'MR05', region: '邮件详情', description: '邮件详情标题' },
  MR06: { id: 'MR06', region: '邮件详情', description: '发件人信息' },
  MR07: { id: 'MR07', region: '邮件详情', description: '收件人/抄送信息' },
  MR08: { id: 'MR08', region: '邮件详情', description: '正文沙箱容器' },
  MR09: { id: 'MR09', region: '邮件详情', description: '附件列表' },
  MR10: { id: 'MR10', region: '邮件详情', description: '详情空状态' },

  // Settings (ST)
  ST01: { id: 'ST01', region: '设置', description: '设置侧栏展开按钮' },
  ST02: { id: 'ST02', region: '设置', description: '设置页面标题' },
  ST03: { id: 'ST03', region: '设置', description: '设置关闭按钮' },
  ST04: { id: 'ST04', region: '设置', description: '设置导航选项卡' },
  ST05: { id: 'ST05', region: '设置', description: '添加账户表单' },
  ST06: { id: 'ST06', region: '设置', description: '外观主题选项' },
  ST07: { id: 'ST07', region: '设置', description: '账号图标展示选项' },
  ST08: { id: 'ST08', region: '设置', description: '通用设置时区与超时' },
  ST09: { id: 'ST09', region: '设置', description: '修改密码表单' },
}

export function isUiReferenceShortcut(e: KeyboardEvent): boolean {
  if (e.repeat) return false
  const hasModifier = e.ctrlKey || e.metaKey
  const hasShift = e.shiftKey
  const isPeriod = e.key === '.' || e.key === '>' || e.code === 'Period'
  return Boolean(hasModifier && hasShift && isPeriod && !e.altKey)
}

export function formatUiReferenceText(id: string): string {
  const meta = UI_ELEMENT_REGISTRY[id]
  if (meta) {
    return `[UI:${meta.id}] ${meta.region} · ${meta.description}`
  }
  return `[UI:${id}] 未知区域 · 未知元素`
}
