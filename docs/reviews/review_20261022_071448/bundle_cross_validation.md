# Critical/High Cross Validation

- Target: kkmail @ `f915e78bcfc81767386f86b5e9f2448235f44fa7`
- Method: second-pass falsification against each finding and its cited implementation/contract; no direct counter-evidence found.

## Results

- AGREE, 99→96: `src/mail_core/api/app.py:68-74`. Default trusted host is `*`; impact requires the app to receive client-supplied forwarded headers without a trusted proxy stripping them. `auth_routes.py:63-68` uses the resulting peer address for rate limiting.
- AGREE, 98→99: `src/mail_core/security/auth.py:347-361,255-281`. Password persistence precedes session epoch invalidation; DB failure in invalidation is logged and swallowed, while the route returns success. Other API processes can continue accepting the prior epoch.
- AGREE, 91→96: `src/mail_core/blobs/gc.py:149-181`. A live-reference check and filesystem unlink are not atomic. If archive commits a reference after the check but before unlink, the DB row survives with a missing blob; the cool-off window does not close this race.
- AGREE, 94→98: `.repo_template/scripts/repo_task/integration.py:221-239` and `worktrees.py:158-188`. Concurrent starts at the same base can make the failed session's compensation remove the successful session's resources because ownership is inferred from branch/base state.
- AGREE, 98→99: `.repo_template/scripts/repo_sync.py:177-180,590-597`. Destination symlinks pass the guard; writes follow them while backup preserves only the symlink.
- AGREE, 95→96: `.repo_template/scripts/repo_cleanup.py:128-136,195-214`. Explicitly selected cleanup roots can be symlinks to external directories; recursive scan and apply operate on their descendants.
- AGREE, 93→99: `.repo_template/scripts/md_format.py:117-145,183-193`. Absolute and traversal paths reach the formatter without resolved-root validation; the usage note is not a runtime guard.
- AGREE, 96→99: `scripts/migrate_from_legacy_db.py:50-58,158-178`. Invalid ciphertext becomes empty text and is persisted; no downstream non-empty validation blocks commit.
- AGREE, 95→99: `scripts/run-mail-core-tests.sh:13-17,30`. `attest` contains the accepted substring, after which the script upgrades the database.
- AGREE, 85→96: `scripts/mail-core-backup-restore-drill.sh:21-42`. Logical `pwd` can preserve an allowed-looking symlink path; `rm -rf` then resolves its parent outside the repository or `/tmp`.
- AGREE, 96→93, severity assessed Medium: `docs/skills/kkmail/scripts/kkmail_cli.py:22,46-52`. Cookie/CSRF values are written without restrictive permissions. Cross-user reads depend on home-directory traversal permissions; a private `0700` home prevents the attack path.

No candidate was challenged. Of the original 11 candidates, ten remain High and the session-cache permissions issue is retained at Medium because it depends on home-directory traversal permissions. The independently checked AccountDTO serialization issue is also High.

- AGREE, 99→99: src/mail_core/api/accounts.py:114-152 与 src/mail_core/mail/application/accounts.py:25-38。带 slots 的 AccountDTO 没有实例 __dict__；列表、创建、更新均无替代序列化路径，分别导致 500 或 400。
