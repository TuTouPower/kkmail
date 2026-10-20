<!-- TRELLIS:START -->
# Trellis Instructions

These instructions are for AI assistants working in this project.

This project is managed by Trellis. The working knowledge you need lives under `.trellis/`:

- `.trellis/workflow.md` — development phases, when to create tasks, skill routing
- `.trellis/spec/` — package- and layer-scoped coding guidelines (read before writing code in a given layer)
- `.trellis/workspace/` — per-developer journals and session traces
- `.trellis/tasks/` — active and archived tasks (PRDs, research, jsonl context)

If a Trellis command is available on your platform (e.g. `/trellis:finish-work`, `/trellis:continue`), prefer it over manual steps. Not every platform exposes every command.

If you're using Codex or another agent-capable tool, additional project-scoped helpers may live in:
- `.agents/skills/` — reusable Trellis skills
- `.codex/agents/` — optional custom subagents

Managed by Trellis. Edits outside this block are preserved; edits inside may be overwritten by a future `trellis update`.

<!-- TRELLIS:END -->

# kkmail 编码代理指南

> 本节在 Trellis 区块之外，`trellis update` 不会覆盖。下列命令均已在干净 clone 中实际跑通（Python 3.13 / Node 20）。

## 项目概况

- kkmail 是 [assast/outlookEmail](https://github.com/assast/outlookEmail) 的二次开发（fork），仓库 `TuTouPower/kkmail`。
- 远端：`origin` = TuTouPower/kkmail，`upstream` = assast/outlookEmail。没有 upstream 时：`git remote add upstream https://github.com/assast/outlookEmail.git`。
- 同步上游：`./scripts/sync-upstream.sh`（合并 `upstream/main` 到 `sync/upstream-main` 并开 PR）；`.github/workflows/upstream-sync.yml` 每周自动开同步 PR。
- **时刻考虑上游合并**：上游代码（`outlook_web/segments/*`、`templates/`、`static/`）尽量少改、改动集中；新功能优先放在新文件/新 segment（如 `12_routes_react_spa.py`）里。产物名与数据目录沿用上游 `OutlookEmail`，不要改名。

## 目录结构

| 路径 | 说明 |
| --- | --- |
| `web_outlook_app.py` | Flask 入口。按文件名顺序把 `outlook_web/segments/NN_*.py` `exec` 进同一个全局命名空间 |
| `outlook_web/segments/` | 后端全部逻辑（路由、IMAP/Graph、调度器）。segment 共享全局变量，`__file__` 是入口模块而不是 segment 本身 |
| `templates/`、`static/` | 旧版界面，挂在 `/legacy`；`/login` 仍是 `templates/login.html` |
| `frontend/` | 新版 SPA：React + TypeScript + Vite，状态 Zustand，数据 `@tanstack/react-query`。构建产物 `frontend/dist` 由 Flask 直接提供 |
| `desktop/` | Electron 壳。启动 PyInstaller 打包的后端 sidecar，并设 `KKMAIL_SIDECAR=1`（后端不再弹托盘/浏览器） |
| `scripts/build-sidecar.sh` | 用 PyInstaller 打包后端 sidecar 到 `desktop/resources/`（含 templates/static/segments/frontend dist） |
| `Dockerfile`、`docker-compose*.yml` | 多阶段构建：Node 构建前端 → python:3.11-slim + gunicorn（`-w 1 --threads 16`，单 worker，上游有进程内状态） |
| `tests/` | pytest；`tests/conftest.py` 负责测试库隔离 |
| `docs/` | 部署、API、安全、已知限制（`docs/known-limitations.md`） |

## 环境与开发

```bash
# 后端
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt

# 前端（构建后由 Flask 提供；vite dev server 没有配置 /api 代理，不适合联调）
cd frontend && npm ci && npm run build && cd ..

# 本地运行（SECRET_KEY 必须显式提供，生产模式下缺失会直接报错）
export SECRET_KEY="$(python -c 'import secrets;print(secrets.token_hex(32))')"
export LOGIN_PASSWORD='换成你的密码' DATABASE_PATH=[REDACTED]dev/dev.db
PORT=5000 HOST=127.0.0.1 python web_outlook_app.py   # http://127.0.0.1:5000
```

- 前端改动后重新 `npm run build` 即可，刷新页面生效；改了 `templates/` 需要重启后端（生产模式缓存模板）。
- `KKMAIL_FRONTEND_DIST=/path/to/dist` 可指定 SPA 目录。
- 换 `SECRET_KEY` 会导致库里已存的 IMAP 密码等无法解密，开发/部署时固定一个 key。

## 测试 / Lint / 类型检查 / 构建

```bash
python -m pytest -q                         # 后端全量（约 30s，770+ 用例）
cd frontend
npm run lint                                # oxlint --deny-warnings
npx tsc -b                                  # 类型检查
npm test                                    # vitest run
npm run build                               # tsc -b && vite build
cd ../desktop && npm ci && npm test          # Electron 路径/导航白名单单测
./scripts/build-sidecar.sh                  # 需先 pip install pyinstaller、已构建 frontend/dist；Debian 系统 Python 还需 apt install libpython3.13
docker build --network host -t kkmail:local .   # 部分环境 bridge 网络下 apt 会失败，用 host 网络构建
```

提交前至少跑：pytest 全量 + 前端 lint / tsc / vitest / build。

## 约定与坑（务必遵守）

- **邮件 HTML 永远不要直接渲染**：只能经 `frontend/src/lib/mailBody.ts`（DOMPurify 清洗 + `buildMailSrcdoc` + `MAIL_IFRAME_SANDBOX` 的 sandbox iframe `srcDoc`）。是否 HTML 只看 `body_type`。禁止 `dangerouslySetInnerHTML`（`tests/test_frontend_mail_body_safety.py` 会检查）。回复/转发引用用 `htmlToText`。
- **邮件唯一键 = 账户 + 文件夹 + id**：一律用 `lib/mailKey.ts` 的 `mailKey()`。IMAP UID 只在单个文件夹内唯一，用 `email:id` 会串邮件/删错邮件。列表项的 `folder` 必须是具体文件夹。
- **CSRF**：写请求走 `api/client.ts` 的 `request()`，自动带 `X-CSRFToken`，遇到 `csrf_error` 会刷新 token 重试一次。Flask cookie session 每个响应都会重写，慢请求可能把 token 冲掉，别绕过这个封装自己 `fetch`。
- **测试不得触碰真实数据库**：`tests/conftest.py` 在导入应用前把 `DATABASE_PATH` 指向临时目录（可用 `KKMAIL_TEST_DATABASE_PATH` 指定）。新测试不要自己改回 `./data`，不要依赖预先构建的 `frontend/dist`（用 `fake_frontend_dist` fixture）。`tests/test_db_isolation.py` 守护这一点。
- **不要硬编码密钥**：`SECRET_KEY`、`LOGIN_PASSWORD` 只从环境变量来；compose 文件里用必填变量，Electron 不注入默认值（桌面版自行生成并持久化）。
- **SPA dist 路径解析必须在 Docker 下可用**：镜像中入口是 `/app/web_outlook_app.py`，不要写 `Path(__file__).parents[2]` 这类固定层级（曾导致容器内所有页面 500）。见 `12_routes_react_spa.py` 的 `_react_dist_dir()`。
- **表单字段**：每个 `input/select/textarea` 必须有 `id` 或 `name`；密码框要有 `autoComplete`，并放在 `<form>` 里。`tests/test_frontend_form_fields.py` 会检查。
- **移动端断点 760px**：与 `lib/viewport.ts` 的 `MOBILE_MAX_WIDTH` 和 `design-system/tokens.css` 的 `@media (max-width: 760px)` 保持一致。≤760px 侧边栏是抽屉（遮罩可点关、Esc 关），对话框全屏；所有导航都走 store 的 `setView` / `openSmartView`，它们会自动关闭抽屉。
- **破坏性操作**先 `confirmAction`，结果用 `ensureSuccess` 检查（后端常返回 HTTP 200 + `success:false`）。
- **UI 文案用中文**（`index.html` 为 `lang="zh-CN"`）；图标按钮要有 `title` 和 `aria-label`。
- **IMAP 账户不能发信**，只有已授权的 Outlook（Graph）账号可以；文案和下拉都要体现（`lib/accounts.ts` 的 `canSendFrom`）。

## 提交规范

Conventional Commits，英文主题行，可带 scope，正文可用中文条目说明：

```
fix(mail): per-folder keys, non-blocking account loading, consistent unread counts
feat: add mobile sidebar drawer and compose CC field
test: isolate test DB globally and drop dependency on a prebuilt frontend
docs: update known limitations and packaging verification
chore: ignore generated PyInstaller sidecar spec
```

常用 scope：`mail`、`ui`、`mobile`、`api`、`server`、`desktop`、`sidecar`、`settings`、`security`、`a11y`。按领域拆分提交，每个提交保持可构建、测试通过。
