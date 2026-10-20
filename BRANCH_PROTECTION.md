# Branch Protection & Release Recommendations

This document records the recommended repository governance settings for `kkmail`. Release steps are in [RELEASE.md](RELEASE.md); release notes come from [CHANGELOG.md](CHANGELOG.md).

## Goal

Prevent accidental direct development on `main`, reduce noisy release/build activity, and make releases more predictable.

## Recommended Branch Roles

- `main`: stable release branch
- `dev`: default development branch

## Recommended GitHub Branch Protection

### Protect `main`

Recommended settings:

- Require a pull request before merging
- Require at least 1 approval (optional if solo-maintained, but recommended if collaborators join later)
- Dismiss stale approvals when new commits are pushed
- Require branches to be up to date before merging
- Restrict direct pushes to `main`
- Restrict force pushes
- Restrict branch deletion

仓库没有 GitHub Actions，所以没有可设为必过的状态检查。合并前在本机跑测试。

### Protect `dev`

Recommended lighter rules:

- Allow direct pushes if the repository is primarily solo-maintained
- Disallow force pushes unless explicitly needed
- Optionally require PRs for larger risky changes

## Suggested Daily Workflow

1. Develop on `dev`
2. Push incremental changes to `dev`
3. Verify app behavior locally
4. Merge `dev` into `main` only for releasable states
5. Update `VERSION` and `CHANGELOG.md`
6. Push a version tag such as `v1.0.1`

## Release Policy

- `main` represents release-ready code
- Version tags (`vX.Y.Z`) represent formal releases
- GitHub Release notes should be sourced from `CHANGELOG.md`
- Avoid tagging if `VERSION`, `CHANGELOG.md`, and actual shipped code are out of sync

## Optional Future Enhancements

- Make `dev` the repository default branch for day-to-day development
- Add manual approval for production image publishing
- Split `latest` and `stable` image semantics if needed
