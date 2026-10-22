#!/usr/bin/env node
import { spawnSync } from 'node:child_process'
import { existsSync, unlinkSync } from 'node:fs'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const schemaCheckFile = resolve(root, 'src/api/generated/schema.check.ts')
const schemaJson = resolve(root, '../../schemas/openapi.json')
const openapiCli = resolve(root, 'node_modules/openapi-typescript/bin/cli.js')
const checkerScript = resolve(root, 'scripts/openapi-check.mjs')

let exitCode = 0

try {
  const genResult = spawnSync(
    process.execPath,
    [openapiCli, schemaJson, '-o', schemaCheckFile],
    {
      cwd: root,
      stdio: 'inherit',
      env: {
        ...process.env,
        NODE_PATH: resolve(root, 'node_modules'),
      },
    },
  )
  if (genResult.status !== 0) {
    exitCode = genResult.status ?? (genResult.error ? 1 : 0)
  } else {
    const checkResult = spawnSync(
      process.execPath,
      [checkerScript],
      {
        cwd: root,
        stdio: 'inherit',
        env: {
          ...process.env,
          NODE_PATH: resolve(root, 'node_modules'),
        },
      },
    )
    if (checkResult.status !== 0) {
      exitCode = checkResult.status ?? (checkResult.error ? 1 : 0)
    }
  }
} catch (err) {
  console.error(err)
  exitCode = 1
} finally {
  if (existsSync(schemaCheckFile)) {
    try {
      unlinkSync(schemaCheckFile)
    } catch {
      // ignore unlink failure in finally
    }
  }
}

if (exitCode !== 0) {
  process.exit(exitCode)
}
