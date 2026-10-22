export interface TokenError {
  variable: string
  file: string
  line: number
}

export interface CheckTokensResult {
  declaredCount: number
  referencedCount: number
  errors: TokenError[]
  ok: boolean
}

const TOKEN_DECL_REGEX = /(--[a-zA-Z0-9_-]+)\s*:/g
const TOKEN_REF_REGEX = /var\(\s*(--[a-zA-Z0-9_-]+)/g

/** Extract all CSS variable declarations from CSS content. */
export function extractDeclaredTokens(cssContent: string): Set<string> {
  const tokens = new Set<string>()
  let match: RegExpExecArray | null
  TOKEN_DECL_REGEX.lastIndex = 0
  while ((match = TOKEN_DECL_REGEX.exec(cssContent)) !== null) {
    tokens.add(match[1])
  }
  return tokens
}

/** Extract all CSS variable references from any file content with line numbers. */
export function extractReferencedTokens(fileContent: string): Array<{ name: string; line: number }> {
  const refs: Array<{ name: string; line: number }> = []
  const lines = fileContent.split('\n')
  for (let i = 0; i < lines.length; i++) {
    const lineText = lines[i]
    TOKEN_REF_REGEX.lastIndex = 0
    let match: RegExpExecArray | null
    while ((match = TOKEN_REF_REGEX.exec(lineText)) !== null) {
      refs.push({ name: match[1], line: i + 1 })
    }
  }
  return refs
}

/** Check a collection of in-memory files against token CSS declarations. */
export function validateCssTokens(
  files: Record<string, string>,
  tokensCssContent: string,
): CheckTokensResult {
  const declared = extractDeclaredTokens(tokensCssContent)
  // Also collect local declarations from CSS files
  for (const [filePath, content] of Object.entries(files)) {
    if (filePath.endsWith('.css')) {
      const localDecl = extractDeclaredTokens(content)
      for (const t of localDecl) declared.add(t)
    }
  }

  const errors: TokenError[] = []
  const referencedSet = new Set<string>()

  for (const [filePath, content] of Object.entries(files)) {
    const refs = extractReferencedTokens(content)
    for (const ref of refs) {
      referencedSet.add(ref.name)
      if (!declared.has(ref.name)) {
        errors.push({
          variable: ref.name,
          file: filePath,
          line: ref.line,
        })
      }
    }
  }

  return {
    declaredCount: declared.size,
    referencedCount: referencedSet.size,
    errors,
    ok: errors.length === 0,
  }
}
