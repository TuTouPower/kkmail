#!/usr/bin/env node
/** Compare freshly generated schema.check.ts to committed schema.ts. */
import { readFileSync, existsSync } from 'node:fs'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const committed = resolve(root, 'src/api/generated/schema.ts')
const fresh = resolve(root, 'src/api/generated/schema.check.ts')

if (!existsSync(committed) || !existsSync(fresh)) {
  console.error('openapi:check missing schema.ts or schema.check.ts; run openapi:gen first')
  process.exit(1)
}
const a = readFileSync(committed, 'utf8')
const b = readFileSync(fresh, 'utf8')
if (a !== b) {
  console.error(
    'frontend/src/api/generated/schema.ts is out of date with docs/openapi.json\n' +
      '  run: scripts/gen-openapi.sh   (or: cd frontend && npm run openapi:gen)',
  )
  process.exit(1)
}
console.log('ok: generated schema.ts matches docs/openapi.json')
