# Bundle Review — dir:src/frontend/src/api_a

- Target: kkmail @ f915e78bcfc81767386f86b5e9f2448235f44fa7
- Coverage: 8 allowlisted tracked files

## Findings

- [Medium][100] src/frontend/src/api/client.ts:251-L251 — SPA 没有用户可见的登出入口 — 证据：API 已实现 logout，但生产代码没有调用点，设置页面也没有登出操作，用户无法主动吊销当前会话。 — 依据：docs/specs/auth_and_session.md AC-004 包含登出及其测试策略。 — 修复：增加可见登出操作，并覆盖调用与会话失效行为。

## Files examined

- src/frontend/src/api/client.csrf.test.ts
- src/frontend/src/api/client.ts
- src/frontend/src/api/mailCore.client.test.ts
- src/frontend/src/api/mailCore.mutations.test.ts
- src/frontend/src/api/mailCore.test.ts
- src/frontend/src/api/mailCore.ts
- src/frontend/src/api/queries.cache.test.ts
- src/frontend/src/api/queries.scope.test.ts
