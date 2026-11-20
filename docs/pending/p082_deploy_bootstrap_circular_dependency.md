---
pid: "p082"
slug: "deploy_bootstrap_circular_dependency"
status: "closed"
resolution: "resolved"
reason: "根因修复：pin_base_images.sh 改为宿主侧校验和固定的 skopeo 按 digest 直导 docker-daemon，移除 alpine:latest 引导容器与 daemon 侧 registry 拉取；lock 固定工具版本/URL/各平台 SHA256，trust policy 入库。红绿：移除两个 base tag 后旧脚本失败（daemon 拉取 alpine:latest i/o timeout），新脚本成功恢复两个 tag；bash -n、新增静态守卫 4 passed、模板契约 388 passed/1 skipped、敏感扫描通过、md/diff check 干净。"
fix_ref: "main"
---
# p082 部署引导自举循环依赖：pin_base_images.sh 依赖未固定且需 daemon 拉取的 alpine:latest

- 现象：2026-11-20 重新部署时 `scripts/deploy_mail_core.sh --no-push` 在不可逆步骤前退出：`pinned base image 'node:22-alpine' is missing from the local daemon; run scripts/pin_base_images.sh`。按提示运行引导脚本不可行：`docker image inspect alpine:latest` 返回 `No such image`；`docker run --rm alpine:latest ...` 报 daemon `Head "https://registry-1.docker.io/v2/library/alpine/manifests/latest": dial tcp ... i/o timeout`。宿主代理 `http://127.0.0.1:7890` 可达（registry 返回 401），但 daemon 按设计无代理。现场用本地已有的 `caddy:alpine` 注入代理 + skopeo 按 lock digest 导入两个 base image 后才完成部署——这是绕行，不是修复。
- 影响：新机器或清空 base image 后，文档规定的部署路径完全不可走；`docs/guides/deployment.md` 声称引导脚本是「全流程唯一联网点、幂等可审计」不成立——底下藏着一次 daemon 侧 registry 拉取。缺陷潜伏到真实重部署才暴露，期间部署脚本的 fail-fast 虽保护了数据与回滚点，但给出的修复指令不可执行。
- 根因：（工具链/部署架构设计缺陷，非部署脚本逻辑错误）
    1. 架构决策是正确的：`config/base_images.lock` 用不可变 index digest 固定 `node:22-alpine`/`python:3.13-slim`，目标是让 BuildKit 从本地命中 FROM、daemon 永不访问 registry。
    2. 但 `scripts/pin_base_images.sh:34-37` 把「如何获得这些固定镜像」这一步划在架构之外：它用 `alpine:latest`（**未固定 tag**）作为引导容器，且必须由 daemon 先拉取该镜像才能启动。引导依赖恰好是主架构要消灭的路径（未固定 tag + daemon registry 访问），形成自举循环依赖。
    3. 在文档自己规定的反向隔离环境（OrbStack `network_proxy none`、daemon 无代理）下，该循环依赖必然失败；`~/.docker/config.json` 的代理只注入 `docker run` 的容器环境，救不了容器启动前的 daemon 拉取。
    4. `deploy_mail_core.sh:73-79` 的断言与 fail-fast 是正确的：它在 push/backup/tag 之前检查并拒绝；问题在于失败信息把用户指向一个在该环境下跑不通的脚本。
    5. 同类位点扫描：全仓仅 `scripts/pin_base_images.sh:34` 一处 `alpine:latest` 与 `docker run -v /var/run/docker.sock`（`grep -rn` 已复核）；未发现第二处同模式。
- 修复方向（治本，非绕行）：把引导从「容器 + daemon 拉取」改为**宿主侧、校验和固定的 skopeo 二进制**直接按 digest 导入 `docker-daemon:`；删除 `alpine:latest` 引导容器；固定 skopeo 版本、下载 URL 与 SHA256；显式 `--override-os linux --override-arch arm64` 以匹配目标 daemon 而非宿主 macOS；用仓库内固定 trust policy 文件避免依赖宿主 `~/.config/containers/policy.json`。这样 bootstrap 也遵守同一不变量：daemon 永不访问 registry、所有输入按 digest/校验和固定、无需任何预置镜像。代价：宿主需能经代理下载工具与镜像层，且需维护工具版本/校验和；不改变容器联网与部署契约。回退：恢复旧脚本即可，镜像导入结果本身不变。
- 测试缺口：现有门禁没有「本地 base image 为空 → 跑 pin 脚本 → 恢复成功」的场景；`deploy_mail_core.sh` 只静态断言 tag 存在，不验证引导路径。应补：其一，静态契约测试锁定「pin 脚本不含 `docker run`/`alpine:latest`、使用 `docker-daemon:` 与锁定校验和」；其二，实测把两个 tag 移除后运行新脚本并 `docker image inspect` 通过（实施期红绿验证），命令与结果写进闭环备注。
- 线索：现场证据 `.scratch/tools/`（临时下载的 crane/skopeo 与 `policy.json`、release JSON，均 gitignore）；关键输出见现象段。复现命令：`docker rmi node:22-alpine python:3.13-slim` 后运行旧 `scripts/pin_base_images.sh`。未改生产配置；本条与 p080/p081 无关。
- 处理：main；resolution=resolved；reason=根因修复：pin_base_images.sh 改为宿主侧校验和固定的 skopeo 按 digest 直导 docker-daemon，移除 alpine:latest 引导容器与 daemon 侧 registry 拉取；lock 固定工具版本/URL/各平台 SHA256，trust policy 入库。红绿：移除两个 base tag 后旧脚本失败（daemon 拉取 alpine:latest i/o timeout），新脚本成功恢复两个 tag；bash -n、新增静态守卫 4 passed、模板契约 388 passed/1 skipped、敏感扫描通过、md/diff check 干净。
