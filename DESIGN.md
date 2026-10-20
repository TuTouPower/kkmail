---
version: alpha
name: Mail Multi-Account
description: A restrained, Apple Mail-inspired design system for a cross-platform multi-account email client.
colors:
  primary: "#0066CC"
  primary-hover: "#0058B8"
  accent: "#0A84FF"
  secondary: "#555961"
  tertiary: "#30D158"
  neutral: "#171819"
  on-primary: "#FFFFFF"
  background-dark: "#171819"
  sidebar-dark: "#1C1D1F"
  list-dark: "#202123"
  reader-dark: "#1D1F20"
  surface-dark: "#27292B"
  surface-container-dark: "#303235"
  hover-dark: "#343639"
  selected-dark: "#34383D"
  text-dark: "#F3F4F5"
  muted-dark: "#96999E"
  subtle-dark: "#C0C2C5"
  border-dark: "#3A3C3F"
  background-light: "#E9EAED"
  sidebar-light: "#F2F3F5"
  surface-light: "#FFFFFF"
  surface-container-light: "#F4F5F7"
  hover-light: "#E9EBEF"
  selected-light: "#E5E7EB"
  text-light: "#1D1D1F"
  muted-light: "#686A70"
  subtle-light: "#555961"
  border-light: "#DADCE0"
  danger-dark: "#FF6B65"
  danger-light: "#D92D20"
  focus: "#0A84FF"
  warning: "#FF9F0A"
typography:
  display:
    fontFamily: "system-ui, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif"
    fontSize: 28px
    fontWeight: 700
    lineHeight: 1.2
    letterSpacing: -0.03em
  title:
    fontFamily: "system-ui, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif"
    fontSize: 20px
    fontWeight: 700
    lineHeight: 1.3
    letterSpacing: -0.02em
  section-title:
    fontFamily: "system-ui, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif"
    fontSize: 16px
    fontWeight: 700
    lineHeight: 1.35
    letterSpacing: -0.01em
  body:
    fontFamily: "system-ui, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif"
    fontSize: 13px
    fontWeight: 400
    lineHeight: 1.6
  body-sm:
    fontFamily: "system-ui, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif"
    fontSize: 12px
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: "system-ui, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif"
    fontSize: 11px
    fontWeight: 600
    lineHeight: 1.4
  caption:
    fontFamily: "system-ui, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif"
    fontSize: 10px
    fontWeight: 400
    lineHeight: 1.45
  timestamp:
    fontFamily: "system-ui, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif"
    fontSize: 10px
    fontWeight: 500
    lineHeight: 1.3
  button:
    fontFamily: "system-ui, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif"
    fontSize: 12px
    fontWeight: 600
    lineHeight: 1.2
  mono:
    fontFamily: "ui-monospace, SFMono-Regular, Consolas, monospace"
    fontSize: 11px
    fontWeight: 400
    lineHeight: 1.5
spacing:
  xxs: 2px
  xs: 4px
  sm: 8px
  md: 12px
  lg: 16px
  xl: 20px
  2xl: 24px
  3xl: 32px
  4xl: 40px
  sidebar-width: 270px
  sidebar-collapsed-width: 48px
  message-list-width: 350px
  mobile-breakpoint: 760px
rounded:
  xs: 4px
  sm: 6px
  md: 8px
  lg: 12px
  xl: 15px
  full: 9999px
components:
  app-shell-dark:
    backgroundColor: "{colors.background-dark}"
    textColor: "{colors.text-dark}"
  app-shell-light:
    backgroundColor: "{colors.background-light}"
    textColor: "{colors.text-light}"
  sidebar-dark:
    backgroundColor: "{colors.sidebar-dark}"
    textColor: "{colors.text-dark}"
    width: "{spacing.sidebar-width}"
    padding: "{spacing.sm}"
  sidebar-light:
    backgroundColor: "{colors.sidebar-light}"
    textColor: "{colors.text-light}"
    width: "{spacing.sidebar-width}"
    padding: "{spacing.sm}"
  sidebar-collapsed-dark:
    backgroundColor: "{colors.sidebar-dark}"
    textColor: "{colors.text-dark}"
    width: "{spacing.sidebar-collapsed-width}"
  message-list-dark:
    backgroundColor: "{colors.list-dark}"
    textColor: "{colors.text-dark}"
    width: "{spacing.message-list-width}"
  message-list-light:
    backgroundColor: "{colors.surface-light}"
    textColor: "{colors.text-light}"
    width: "{spacing.message-list-width}"
  reader-pane-dark:
    backgroundColor: "{colors.reader-dark}"
    textColor: "{colors.text-dark}"
  reader-pane-light:
    backgroundColor: "{colors.surface-light}"
    textColor: "{colors.text-light}"
  list-toolbar-dark:
    backgroundColor: "{colors.surface-container-dark}"
    textColor: "{colors.text-dark}"
    padding: "{spacing.md}"
  list-toolbar-light:
    backgroundColor: "{colors.surface-container-light}"
    textColor: "{colors.text-light}"
    padding: "{spacing.md}"
  message-row-dark:
    backgroundColor: "{colors.list-dark}"
    textColor: "{colors.text-dark}"
    rounded: "{rounded.md}"
    padding: "{spacing.md}"
  message-row-hover-dark:
    backgroundColor: "{colors.hover-dark}"
    textColor: "{colors.text-dark}"
    rounded: "{rounded.md}"
  message-row-hover-light:
    backgroundColor: "{colors.hover-light}"
    textColor: "{colors.text-light}"
    rounded: "{rounded.md}"
  message-row-selected:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.on-primary}"
    rounded: "{rounded.md}"
    padding: "{spacing.md}"
  filter-chip-dark:
    backgroundColor: "{colors.surface-container-dark}"
    textColor: "{colors.subtle-dark}"
    rounded: "{rounded.sm}"
    padding: "{spacing.sm}"
  filter-chip-active-dark:
    backgroundColor: "{colors.selected-dark}"
    textColor: "{colors.text-dark}"
    rounded: "{rounded.sm}"
    padding: "{spacing.sm}"
  filter-chip-light:
    backgroundColor: "{colors.surface-container-light}"
    textColor: "{colors.muted-light}"
    rounded: "{rounded.sm}"
    padding: "{spacing.sm}"
  filter-chip-active-light:
    backgroundColor: "{colors.selected-light}"
    textColor: "{colors.text-light}"
    rounded: "{rounded.sm}"
    padding: "{spacing.sm}"
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.on-primary}"
    rounded: "{rounded.md}"
    padding: "{spacing.sm}"
    height: 35px
  button-primary-hover:
    backgroundColor: "{colors.primary-hover}"
    textColor: "{colors.on-primary}"
    rounded: "{rounded.md}"
    padding: "{spacing.sm}"
    height: 35px
  button-secondary-dark:
    backgroundColor: "{colors.surface-dark}"
    textColor: "{colors.text-dark}"
    rounded: "{rounded.md}"
    padding: "{spacing.sm}"
    height: 34px
  button-secondary-light:
    backgroundColor: "{colors.surface-light}"
    textColor: "{colors.secondary}"
    rounded: "{rounded.md}"
    padding: "{spacing.sm}"
    height: 34px
  icon-button-dark:
    backgroundColor: "{colors.surface-container-dark}"
    textColor: "{colors.subtle-dark}"
    rounded: "{rounded.md}"
    size: 34px
  icon-button-light:
    backgroundColor: "{colors.surface-light}"
    textColor: "{colors.subtle-light}"
    rounded: "{rounded.md}"
    size: 34px
  search-input-dark:
    backgroundColor: "{colors.surface-dark}"
    textColor: "{colors.text-dark}"
    rounded: "{rounded.md}"
    padding: "{spacing.sm}"
    height: 34px
  search-input-light:
    backgroundColor: "{colors.surface-light}"
    textColor: "{colors.text-light}"
    rounded: "{rounded.md}"
    padding: "{spacing.sm}"
    height: 34px
  settings-panel-dark:
    backgroundColor: "{colors.surface-dark}"
    textColor: "{colors.text-dark}"
    rounded: "{rounded.xl}"
    padding: "{spacing.xl}"
  settings-panel-light:
    backgroundColor: "{colors.surface-light}"
    textColor: "{colors.text-light}"
    rounded: "{rounded.xl}"
    padding: "{spacing.xl}"
  metadata-dark:
    backgroundColor: "{colors.list-dark}"
    textColor: "{colors.muted-dark}"
    typography: "{typography.caption}"
  metadata-light:
    backgroundColor: "{colors.surface-light}"
    textColor: "{colors.muted-light}"
    typography: "{typography.caption}"
  danger-action-dark:
    backgroundColor: "{colors.surface-dark}"
    textColor: "{colors.danger-dark}"
    rounded: "{rounded.md}"
    padding: "{spacing.sm}"
  danger-action-light:
    backgroundColor: "{colors.surface-light}"
    textColor: "{colors.danger-light}"
    rounded: "{rounded.md}"
    padding: "{spacing.sm}"
  divider-dark:
    backgroundColor: "{colors.border-dark}"
    height: 1px
  divider-light:
    backgroundColor: "{colors.border-light}"
    height: 1px
  unread-indicator:
    backgroundColor: "{colors.accent}"
    size: 6px
  focus-indicator:
    backgroundColor: "{colors.focus}"
    size: 2px
  status-success:
    backgroundColor: "{colors.tertiary}"
    textColor: "{colors.neutral}"
  status-warning:
    backgroundColor: "{colors.warning}"
    textColor: "{colors.neutral}"
---

> **Scope:** this file is the UI design system (tokens, components, layout) and is not a system design. System architecture lives in [docs/mail-core-architecture.md](docs/mail-core-architecture.md); backend modules in [mail_core/README.md](mail_core/README.md). The action inventory below (compose, reply, forward, archive, junk, move, standard folders) is the visual reference for where controls belong; what the product actually ships is listed in [docs/known-limitations.md](docs/known-limitations.md). Tokens are implemented in `frontend/src/design-system/tokens.css`.

# Mail Multi-Account — Design System

## Overview

Mail is a multi-account email workspace inspired by the clarity, density, and restrained native feel of Apple Mail. It should feel focused, reliable, quiet, and efficient—not like a dashboard full of cards. The product is intended to run as a desktop application on macOS, Windows, and Linux, and as a responsive web application served from Docker. The same design language must work with a mouse, keyboard, touch input, and narrow mobile viewports.

The interface prioritizes the email itself. Avoid a permanent branded masthead: no decorative logo or product-name row at the top of the workspace. Use available vertical space for mail navigation, message lists, and reading. The sidebar starts with a compact collapse control above Personal Favorites. Settings live behind one settings entry at the bottom of the sidebar; account management and appearance preferences belong inside that settings surface rather than scattered across the main chrome.

The information architecture has three desktop regions: a navigation sidebar, a message list, and a reading pane. The sidebar supports independently collapsible account groups and independently collapsible accounts, with standard folders nested under each account. The message list owns list-scoped controls such as search, filtering, sorting, refresh, compose, selection, and Mark All as Read. The reading pane owns actions that affect the current message, including reply, reply all, forward, mark read/unread, archive, trash, junk, move, flag, and secondary actions. A given action should have one obvious home; do not duplicate the same primary action in multiple toolbars.

Dark mode is the default visual reference for the current prototype. Light mode is a first-class theme, not an afterthought. Use semantic tokens rather than hard-coded color values so both themes remain consistent. The product must not rely on Apple-only APIs or platform-specific window chrome for core interaction; platform-native polish is welcome, but interaction and hierarchy must remain consistent across operating systems and browsers.

## Colors

The palette uses layered charcoal surfaces in dark mode and cool neutral surfaces in light mode. A single blue family identifies the primary action, focus, unread indicators, and active navigation. Filled buttons and selected message rows use a deeper, high-contrast blue; the brighter system blue is reserved for icons, focus indicators, and small emphasis. Green is reserved for positive connection or synchronization status. Red is reserved for destructive actions and security-critical errors. Avoid adding a second competing accent color.

- **Primary (`#0066CC`):** high-contrast blue for filled primary actions and selected message rows with white foreground text.
- **Accent (`#0A84FF`):** brighter blue for focus indicators, unread dots, active icons, and subtle interactive emphasis.
- **Secondary (`#555961`):** readable secondary text in the light theme and utility controls.
- **Tertiary (`#30D158`):** positive status only, such as a healthy connection indicator.
- **Neutral (`#171819`):** deepest base neutral for the dark workspace.
- **Dark surfaces:** use separate tokens for the application canvas, sidebar, list, reader, elevated controls, and hover states. Do not flatten the entire application to one charcoal value.
- **Light surfaces:** use a cool-gray canvas and sidebar with white list and reading surfaces. Keep dividers subtle but visible against both white and gray backgrounds.
- **Text:** primary text must be strong and readable. Muted text is for timestamps, account metadata, helper copy, and secondary counts—not for essential content or action labels.
- **Contrast:** target WCAG 2.2 AA for normal text (at least 4.5:1) and 3:1 for large text and meaningful non-text controls. Never communicate unread, selected, failed, or connected state through color alone; pair color with shape, weight, iconography, or text.

## Typography

Use the system UI font stack to keep the interface crisp and familiar on macOS, Windows, Linux, and mobile browsers. Do not load a remote font just for the prototype. Allow the operating system to choose its native UI font; keep the scale and weight consistent across platforms.

- **Display and page titles:** bold and compact, with slightly negative tracking. Use sparingly for folder titles and major settings headings.
- **Message subjects and senders:** use medium-to-bold weight to establish a clear reading hierarchy. Unread sender and subject text may use a stronger weight, with a small unread dot as a second cue.
- **Body text:** comfortable line-height for email content. The reading pane should preserve the email's content hierarchy rather than styling every paragraph like application chrome.
- **Labels and metadata:** compact but legible. Timestamps, provider names, unread counts, and helper text may use 10–12px sizing, but never reduce essential interactive labels below a comfortable touch size.
- **Email content:** keep message content distinct from application controls. Preserve line breaks, links, quoted content, and attachment names. Do not force all email HTML into the same visual treatment as the app's own UI.
- **Font weights:** use a restrained range—regular for body copy, medium for controls and metadata, bold for hierarchy. Avoid mixing many weights in a single view.

The `typography` tokens define reusable roles, not mandatory HTML tags. Map them to semantic UI roles in the implementation and preserve readable fallback fonts for Chinese, Japanese, and other localized text.

## Layout

### Desktop and wide web

Use a three-column workspace that fills the viewport height: sidebar, message list, and reader. The default target widths are 270px for the sidebar and 350px for the message list; the reader takes the remaining space and must be allowed to shrink without forcing the whole page to scroll horizontally. The sidebar and message list scroll independently from the reading pane. Use thin dividers to distinguish columns instead of heavy card shadows.

The sidebar can collapse to a narrow 48px rail. Its collapse control must remain visible in the rail so users can restore navigation. Place this control above the Personal Favorites label. Do not introduce a global application title bar inside the web layout; native window controls belong to the desktop shell, if a desktop wrapper is used.

### Message list

The list header contains the current folder or account title and message counts, with compose and refresh controls nearby. Search spans all mail sources by default and should have a clear action when a query is present. Filters (All, Unread, Flagged), Mark All as Read, sorting, and list-level selection actions remain grouped in the list header. Mark All as Read affects the current visible scope—respecting the selected account/folder and active search or filters—and should be disabled when there are no unread messages in that scope.

Message rows should be compact but scannable. Use a consistent order: sender and timestamp, subject, preview, then account/folder metadata and compact status icons. Truncate long subjects and previews gracefully. Hover, keyboard focus, selected, checked, and unread states must be visually distinct. Selection checkboxes may appear on hover on desktop, but should remain easy to discover and operate on touch devices.

### Reading pane and actions

The reading pane has its own compact toolbar for the currently selected message. Keep message-specific actions together and avoid repeating them in the list header. Destructive actions should be visually separated from routine reply actions. The message body gets a readable maximum width and generous line-height; long emails should scroll within the reader rather than pushing the overall app beyond the viewport. External or remote message content must not load silently; communicate when remote content is blocked and provide an explicit user action where supported.

### Settings and account management

The bottom-left sidebar control is Settings. Account management, add-account flows, appearance, theme choice, and general preferences belong in the settings panel. Do not place separate theme or account-management buttons in the global chrome or duplicate them beside Settings. Settings should use a clear category navigation and a content area; on narrow screens, categories may become a compact horizontal tab row.

### Responsive behavior

- **Above 1180px:** show all three columns at the default target widths.
- **761–1180px:** preserve three columns but allow the sidebar and list to narrow. Hide redundant text labels before hiding important actions; keep tooltips or accessible names on icon-only controls.
- **760px and below:** switch to a single primary pane at a time. The message list is the default view; selecting a message opens the reader, and a clear back control returns to the list. The sidebar becomes a drawer opened by a navigation control in the list header. Use safe-area padding on mobile and avoid horizontal page scrolling.
- **Touch targets:** aim for 40–44px for primary touch targets on mobile where space permits. Icon-only controls must have an accessible name and a visible focus state.
- **Responsive content:** allow long email addresses and subjects to wrap or truncate without covering controls. Modals must fit within the viewport and scroll internally when necessary.

## Elevation & Depth

Use tonal separation first and shadows second. Column boundaries and panel boundaries are defined by thin neutral dividers. Hover and selection states use surface changes, not large elevation jumps. Reserve a soft, stronger shadow for overlays such as Settings, compose, and contextual menus so they read as temporary layers above the workspace.

Avoid stacking cards inside cards. The email client is a dense productivity tool; the list itself should remain a continuous surface, with individual message rows separated primarily by spacing and subtle state backgrounds. Popovers and modals must have enough contrast from the content behind them and must close predictably with Escape or an explicit close action.

## Shapes

Use a consistent, moderately rounded shape language. Small controls and filter chips use 6–8px radii, message rows and inputs use 8px, larger panels and modals use 12–15px, and avatars/status dots may use full rounding. Do not mix sharp, square corners with highly pill-shaped controls without a clear semantic reason.

Borders are thin and low-contrast at rest, but must become more visible on hover, keyboard focus, selected states, and validation errors. Focus rings should be clearly visible against both themes and must not rely on a subtle shadow alone. Icons use a consistent outlined stroke style and should be optically centered; avoid mixing filled and outlined styles for equivalent actions unless the filled form communicates an active state, such as a flagged message.

## Components

### Navigation and account tree

- **Sidebar collapse control:** one compact control at the very top of the sidebar, above Personal Favorites. Keep it available when the sidebar is collapsed.
- **Account group:** group label, disclosure control, and optional account count. Collapsing a group hides its account rows but does not alter account state or folder contents.
- **Account row:** provider mark, email address, unread count, and independent disclosure control. Clicking the account identity opens its inbox; clicking its disclosure control only expands or collapses its folder tree.
- **Folder row:** consistent icon, label, and optional unread count. Active folder/account context must be obvious without relying on text color alone.
- **Settings entry:** a single bottom-left button. Account management and theme selection are subpages inside Settings, not independent persistent sidebar buttons.

### Toolbars and actions

- **List toolbar:** compose, refresh, search, list filters, sorting, Mark All as Read, and list selection / overflow actions. These operate on the current list scope.
- **Reader toolbar:** reply, reply all, forward, mark read/unread, archive, trash, junk, move, flag, and secondary actions. These operate on the selected message or explicitly selected message set.
- **No duplicated actions:** do not repeat reply/forward controls both in the reader toolbar and again as a second row at the bottom of the same message. Do not repeat refresh, search, theme, or account management across multiple persistent toolbars.
- **Primary button:** use the primary blue only for the most important commit action in a modal or flow. Secondary actions use neutral surfaces and subtle borders.
- **Icon button:** use an outlined icon, consistent dimensions, hover feedback, accessible label, tooltip where appropriate, and visible keyboard focus. Icon-only buttons must not be ambiguous.
- **Mark All as Read:** place beside list-level controls near the message count and filters, not in the reader toolbar. It acts on the current visible scope and reports how many messages were updated.
- **Move menu:** show the destination folder names, close after a successful selection, and provide clear feedback.

### Search, filters, and message rows

- **Search input:** sits in the list header, has a search icon, keyboard focus state, and a clear button only when non-empty. Search should not consume the reader toolbar's space.
- **Filter chips:** All, Unread, and Flagged are mutually exclusive. Use a selected surface and text weight to indicate the active filter.
- **Unread state:** use a small blue dot and stronger sender/subject weight. Do not make the unread state depend on bold text alone.
- **Flagged state:** use the flag icon and an accessible label. The icon should not compete with the sender or timestamp.

> Implementation note: flags are server-side (`is_flagged`, written back to IMAP/Gmail/Graph); the Flagged filter reads that field.
- **Attachments:** show a compact attachment indicator in the list and a clear file name/type/size treatment in the reader.
- **Empty state:** explain why no messages are shown and offer a relevant next action, such as clearing search or changing folders.

### Settings, dialogs, and feedback

- **Settings panel:** categories for Account Management, Appearance, and General. Theme selection is available here only. Display the current theme and mark the selected option clearly.
- **Account management:** list configured accounts with provider, address, group, and connection state. Add/remove/re-authorize actions must be explicit. Never ask users to type account passwords into a generic front-end dialog; use provider OAuth or a secure backend-managed connection flow in production.
- **Compose dialog:** clear sender identity, recipient, CC, subject, and body fields. Keep Send as the primary action and Save Draft as secondary. Make the sending state and errors explicit.
- **Toast feedback:** acknowledge successful local actions such as archive, move, theme change, and mark-as-read. Do not claim a real email was sent or synchronized unless the backend confirms it.
- **Responsive dialog:** use a bounded viewport height with internal scrolling. On mobile, avoid a desktop-width dialog that overflows the screen.

The following component tokens are the implementation reference for recurring controls and surface states. They are semantic targets; theme-specific tokens should be used instead of hard-coded values in new components.

## Do's and Don'ts

- **Do** remove the branded top masthead from the main workspace; do not add a logo or product name above the three-column layout.
- **Do** place the sidebar collapse control above Personal Favorites and keep it available when collapsed.
- **Do** keep Settings as the single bottom-left entry point for account management, theme, and general preferences.
- **Do** separate list-level actions from current-message actions. Every persistent toolbar button must have one clear scope.
- **Do** put Mark All as Read next to list filters and counts, and restrict its effect to the current visible list scope.
- **Do** support dark and light themes with semantic tokens and test both independently.
- **Do** design desktop, tablet, and mobile layouts as first-class experiences; do not assume every user has a wide screen or a mouse.
- **Do** preserve keyboard navigation, visible focus, descriptive accessible names, and readable contrast.
- **Do** keep long account addresses, subjects, and previews from overlapping adjacent controls.
- **Do** distinguish simulated demo actions from confirmed backend operations in user-facing feedback.
- **Don't** repeat the same reply, forward, archive, trash, search, refresh, theme, or account-management action in multiple persistent toolbars.
- **Don't** add decorative header rows, duplicate branding, redundant buttons, or controls that have no meaningful behavior.
- **Don't** use color alone to represent unread, selected, flagged, connected, warning, or error states.
- **Don't** place account management or theme switching as separate permanent buttons beside the Settings entry.
- **Don't** let message HTML or remote content silently execute or load without a deliberate, secure content policy.
- **Don't** imply that demo-only send, sync, download, or account-connect controls operate on real accounts.
