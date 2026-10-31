# p069 远程图片代理提取与容错缺陷：无引号 src、实体不一致、协议相对、错误分类、SVG 与 IP 回退

- 现象：部署 t068 后，发件人已在白名单（`noreply-accounts@google.com`）、邮件处于已放行状态，正文所有外链图片仍显示碎图。Google 通知邮件 `<img>` 使用 HTML5 合法无引号属性（`<img src=https://www.gstatic.com/... height=40`），服务端未生成任何 `remote_images` 代理映射，前端无 URL 可重写，图片保留外部 URL 后被正文 CSP `img-src 'self' data: cid:` 拦截。
- 影响（L1 全库量化，19897 封有正文 / 18389 封含 `<img>`）：
    1. 主缺陷 F1（无引号 src）：`_IMG_SRC_RE` 强制要求引号，`src=https://...` 一律漏提取。**558 封提取为 0（全部碎图）**，**2519 封部分漏提取**。生产复现邮件 `d63b93a8-88ed-4d2b-9efe-4e2f76dcc4c7` 正文 9 个 `<img>` 全部无引号，`extract_remote_image_urls` 返回 `0`。
    2. F2（HTML 实体不一致）：后端正则从原始 HTML 提取，保留 `&amp;`；前端 DOMParser `getAttribute('src')` 已解码为 `&`，精确匹配 `mapping.has(src)` 必失败。**2874 封**含 `&` 实体的图片 URL 放行后仍碎图。
    3. F3（协议相对 URL）：后端只匹配 `https?://`，前端 `hasRemoteImages` 却识别 `//`。实测 `<img src="//cdn.test/p.png">` 提取为 `[]`，**2 封**仅协议相对；出现「有拦截横幅但永远无映射」的不一致。
    4. F4（错误分类混淆）：DNS 解析失败被包装为 `SSRFSecurityError` → 400；上游 4xx/409 直接抛 `RemoteImageFetchError` → 502。L2 探针 800 URL 中 22 个实际是 DNS 失效而非 SSRF 拦截，诊断与 UX 无法区分「网络不可达 / 上游拒绝 / 安全拦截」。同文件 `fetch_safe_remote_image` 只连 `safe_ips[0]`，`getaddrinfo` 返回 IPv6 优先且环境无 IPv6 出网时直接 502（机制已实测：容器内 IPv6 地址 `Network is unreachable`，`lh3` 当前 IPv4 排首未触发；属 F5 隐患）。
    5. F5（IP 回退）：见上，单一 `safe_ips[0]` 无按序回退尝试。
    6. F6（SVG 误伤）：代理按设计拒绝 `image/svg+xml`。L2 实测 `https://rescdn.qqmail.com/qqmail/images/unrealname.svg` 返回合法 `image/svg+xml`（浏览器 UA 200），被代理 415 → 碎图。`<img>` 上下文加载 SVG 不执行脚本，叠加 `nosniff` + CSP `img-src` 属安全可放行范围；当前策略误伤**16/800 抽样 URL**（QQ 邮箱模板占位头像等）。
    7. 非缺陷（不修，浏览器直连同样失败）：L2 中上游 404/403/409（防盗链、动态过期追踪像素）、连接超时、DNS 已失效域名。`network_error` 107 例深挖为 `services.google.com` / `render.com` 全 IP TCP 超时等本机网络不可达，与代码无关。
- 根因：服务端图片 URL 提取用手写正则而非 HTML5 解析语义（无引号值合法、字符引用需解码、协议相对需补全），且与前端 DOMParser 取值不保证字节一致；错误分类把网络/DNS/上游失败与安全拦截混为一类；SVG 安全策略过度收紧；连接层缺少多 IP 回退。
- 已验证非 SSRF/网络原因：容器内直接 `fetch_safe_remote_image` 拉取该邮件两张图均成功（`image/png`，8493 / 1986 字节）；L3 生产 CSP + 生产代理端点 + 真实 Chromium 渲染两张图均 `naturalWidth` 160 / 512，零 CSP 违规。
- 测试缺口：
    - 后端 `test_extract_remote_image_urls` 只覆盖带引号理想 HTML，未覆盖无引号、实体、协议相对、混合属性。
    - 前端 `rewriteRemoteImages` 单测只覆盖 key 完全相等，未覆盖 `&amp;` / `//` / 空白差异。
    - E2E 夹具 `tests/e2e/stubApi.ts` 全用带引号 `src`，无法暴露真实邮件形态；需新增无引号 + 实体 + 协议相对夹具并在真实 CSP 下断言 `naturalWidth > 0`。
    - 缺 DNS 失败 / 上游 4xx / 单 IP 不可达的错误分类断言与 SVG 放行断言。
- 线索（均在本仓库 `.scratch/`，已 gitignore）：
    - `p069_google_mail.html`：生产原文 56 KB，9 个无引号 `<img>`。
    - `p069_l1_scan.py`：全库量化（19897 封；558 / 2519 / 2874 / 2）。
    - `p069_l2_probe.py` + `p069_l2_deep.py` + `p069_l2_net.py`：800 URL 真实试拉与失败分类。
    - `p069_l3_probe.mjs` + `p069_l3_urls.txt`：生产 CSP 下真实解码验证（naturalWidth 160/512，0 CSP 违规）。
- 处理：t069
