# kkmail 编码代理指南

> 本节在 Trellis 区块之外，`trellis update` 不会覆盖。下列命令均已在干净 clone 中实际跑通（Python 3.13 / Node 20）。

## 项目概况

- kkmail 是 [assast/outlookEmail](https://github.com/assast/outlookEmail) 的二次开发（fork），仓库 `TuTouPower/kkmail`。
- **邮件内核是 `mail_core/`（FastAPI + Postgres + worker）**；Flask `web_outlook_app.py` / `outlook_web/segments/` 已删除；勿再恢复 exec segment 结构。
- 远端：`origin` = TuTouPower/kkmail，`upstream` = assast/outlookEmail。
- 新功能只进 `mail_core/` 与 `frontend/`；不要再扩大 Flask segment 表面积。产物名与数据目录仍可能沿用上游 `OutlookEmail`。

## 目录结构

| 路径 | 说明 |
| --- | --- |
| `mail_core/` | **主后端**：FastAPI API、worker、同步、blob、鉴权（Cookie Session + Bearer API Key） |
| `frontend/` | React SPA（唯一 UI）。构建产物 `frontend/dist` |
| `docker-compose.mail-core.yml` | Postgres + API + worker 开发栈（密钥均需环境变量） |
| `web_outlook_app.py` / `outlook_web/segments/` | 已删除（`web_outlook_app.py` 仅为提示 shim） |
| `templates/`、`static/` | 遗留 UI（`/legacy`）；勿再扩展 |
| `desktop/` | Electron 壳 |
| `tests/mail_core/` | mail-core pytest；根 `tests/` 多为 Flask 遗留契约 |
| `docs/` | 架构见 `docs/mail-core-architecture.md`；CI 模板见 `docs/ci/` |
| `docs/ci/` | 工作流模板（仓库可能缺 workflow 写权限时在此维护，再人工同步到 `.github/workflows`） |

## 环境与开发

```bash
# mail-core（推荐）
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-mail-core.txt
export MAIL_CORE_SECRET_KEY="$(openssl rand -hex 32)"
export MAIL_CORE_LOGIN_PASSWORD='换成你的密码'
export MAIL_CORE_BLOB_KEY_V1="$(python3 -c 'import os,base64;print(base64.b64encode(os.urandom(32)).decode())')"
# 另需 Postgres：见 docker-compose.mail-core.yml / scripts/run-mail-core-tests.sh
uvicorn mail_core.api.app:app --host 127.0.0.1 --port 8000
python -m mail_core.worker.main

# 前端
cd frontend && npm ci && npm run build && cd ..

# 遗留 Flask 壳（账号管理等未迁完时）
pip install -r requirements-dev.txt
export SECRET_KEY="$(openssl rand -hex 32)" LOGIN_PASSWORD='换成你的密码'
PORT=5000 HOST=127.0.0.1 python web_outlook_app.py
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
