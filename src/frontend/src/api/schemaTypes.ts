/**
 * Convenient aliases over OpenAPI-generated components.
 * HTTP DTO shapes live here; UI view-models (MailItem, MailDetail) stay in queries.ts.
 */
import type { components } from './generated/schema'

export type schemas = components['schemas']

export type AccountOut = schemas['AccountOut']
export type AccountsPage = schemas['AccountsPage']
export type AccountCreateIn = schemas['AccountCreateIn']
export type AccountUpdateIn = schemas['AccountUpdateIn']
export type AttachmentOut = schemas['AttachmentOut']
export type GroupOut = schemas['GroupOut']
export type GroupsOut = schemas['GroupsOut']
export type GroupCreateIn = schemas['GroupCreateIn']
export type LoginIn = schemas['LoginIn']
export type LoginOut = schemas['LoginOut']
export type MeOut = schemas['MeOut']
export type MessageOut = schemas['MessageOut']
export type MessageDetailOut = schemas['MessageDetailOut']
export type MutationOut = schemas['MutationOut']
export type PageOut = schemas['PageOut']
export type SearchPageOut = schemas['SearchPageOut']
export type SettingsOut = schemas['SettingsOut']
export type SettingsUpdateIn = schemas['SettingsUpdateIn']
export type SyncAllOut = schemas['SyncAllOut']
export type SyncJobOut = schemas['SyncJobOut']
export type HealthOut = schemas['HealthOut']
export type ReadyOut = schemas['ReadyOut']
export type ReadBody = schemas['ReadBody']
export type FlagBody = schemas['FlagBody']
export type PasswordChangeIn = schemas['PasswordChangeIn']
export type AccountFolderStatsOut = schemas['AccountFolderStatsOut']
export type AccountFolderStatsItemOut = schemas['AccountFolderStatsItemOut']
export type AccountInboxStatsOut = schemas['AccountInboxStatsOut']
export type GlobalStatsOut = schemas['GlobalStatsOut']
export type SidebarLayoutSnapshotOut = schemas['SidebarLayoutSnapshotOut']
export type OAuthMetadataOut = schemas['OAuthMetadataOut']
export type OAuthStartIn = schemas['OAuthStartIn']
export type OAuthStartOut = schemas['OAuthStartOut']
export type OAuthFlowStatusOut = schemas['OAuthFlowStatusOut']
export type OAuthActiveOut = schemas['OAuthActiveOut']
export type OAuthCancelOut = schemas['OAuthCancelOut']

/** Previous hand-written names → OpenAPI schemas (API layer). */
export type MailCoreMessage = MessageOut
export type MailCoreInboxPage = PageOut
export type MailCoreSearchPage = SearchPageOut
export type MailCoreAttachment = AttachmentOut
export type MailCoreMessageDetail = MessageDetailOut
export type MutationResult = MutationOut
export type AccountSummary = AccountOut
export type AccountsResponse = AccountsPage
export type GroupsResponse = GroupsOut
export type SyncAllResponse = SyncAllOut
