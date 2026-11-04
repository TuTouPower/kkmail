/**
 * A354: diagnostic stacks are copied out of the app for troubleshooting,
 * so strip directory structure (home dirs, project layout, drive paths,
 * dev-server URLs) down to the bare file name before a stack is stored.
 * Line/column suffixes stay attached to the file name segment.
 */
export function trimStackPaths(stack: string): string {
  const keepFileName = (token: string): string => {
    const parts = token.split(/[\\/]/).filter(Boolean)
    return parts.length ? parts[parts.length - 1] : token
  }
  return stack
    .replace(/https?:\/\/[^\s)]+/g, keepFileName)
    .replace(/(?:[A-Za-z]:[\\/]|\/)[^\s()]+/g, keepFileName)
}
