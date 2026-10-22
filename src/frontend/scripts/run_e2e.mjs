#!/usr/bin/env node
import { spawnSync } from 'node:child_process'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const cli = resolve(root, 'node_modules/@playwright/test/cli.js')

const args = process.argv.slice(2)
const targets = args.length > 0 ? args : ['smoke.spec.ts', 'sidebar_tree.spec.ts']

const result = spawnSync(
  process.execPath,
  [cli, 'test', ...targets],
  {
    cwd: root,
    stdio: 'inherit',
    env: {
      ...process.env,
      NODE_PATH: resolve(root, 'node_modules'),
    },
  },
)

process.exit(result.status ?? (result.error ? 1 : 0))
