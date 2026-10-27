"""task 调度看板本地服务。

只读；stdlib http.server；无 WebSocket、无后台轮询。每次请求重新计算
schedule，页面通过注入 JSON 交给客户端 JS 渲染；静态资源（board.css /
board.js）从同目录 view_static/ 读取，无构建、无 CDN 依赖。
"""

import json
import os
import platform
import secrets
import socket
import subprocess
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import repo_task.context as ctx

from .plan import (
    CATEGORIES,
    build_board_model,
    classify_node,
    compute_batch_plan,
)
from .scheduling import compute_schedule
from .store import discover_effective_sources, git_text_at_ref

_STATIC_DIR = Path(__file__).resolve().parent / "view_static"
_DOC_NAMES = {"spec": "spec.md", "task": "task.md"}

# A29: /task-doc 一次性访问 token。serve() 启动时生成，经看板页面注入
# window.__DOC_TOKEN__，board.js 请求 /task-doc 时以查询参数携带；未启动
# serve 的嵌入/测试场景为 None，此时不做 token 校验（Host/Origin 校验仍生效）。
_DOC_TOKEN: str | None = None


class _ThreadingHTTPServerV6(ThreadingHTTPServer):
    """IPv6 版 ThreadingHTTPServer：仅切换地址族，其余行为一致。"""

    address_family = socket.AF_INET6


def _server_class_for_host(host: str):
    """按 host 字面选择服务器类：含 ``:`` 的 IPv6 字面量必须用 AF_INET6，
    否则 _is_loopback_host 认可的 ::1 用 AF_INET 服务器必然绑定失败。"""
    normalized = (host or "").strip().strip("[]")
    return _ThreadingHTTPServerV6 if ":" in normalized else ThreadingHTTPServer


def _build_model():
    """调度图 → 前端模型：节点、边、统计 + 后端权威 plan。

    使用本模块 ``compute_schedule`` 引用，便于测试 monkeypatch。
    """
    model = build_board_model(compute_schedule())
    model["plan"] = compute_batch_plan(model)
    return model


def _render_html(model: dict) -> str:
    """纯函数：读取模板，注入模型 JSON（转义 </script> 防闭合注入）
    与 /task-doc 访问 token（A29）。"""
    template = (_STATIC_DIR / "board.html").read_text(encoding="utf-8")
    payload = json.dumps(model, ensure_ascii=False).replace("</", "<\\/")
    html = template.replace("__BOARD_JSON__", payload)
    # 占位符须与标识符 window.__DOC_TOKEN__ 区分，否则 replace 会连标识符一起替换
    return html.replace("__DOC_TOKEN_JSON__", json.dumps(_DOC_TOKEN or ""))


def _allowed_doc_roots(base: Path) -> tuple[Path, ...]:
    """任务文档允许的根：主仓用 ctx 常量（测试可 monkeypatch），worktree 用其自身路径。"""
    if base.resolve() == ctx.REPO_ROOT.resolve():
        return (ctx.TASKS_DIR.resolve(), ctx.ARCHIVE_TASKS_DIR.resolve())
    return (
        (base / "docs" / "tasks").resolve(),
        (base / "docs" / "archive" / "tasks").resolve(),
    )


def _resolve_task_doc_in(base: Path, tasks: dict[str, dict], tid: str, doc: str) -> Path:
    """在给定工作区根下校验并解析任务文档路径；非法请求抛 ctx.TaskDataError。"""
    if tid not in tasks:
        raise ctx.TaskDataError(f"未知任务 {tid!r}")
    filename = _DOC_NAMES.get(doc)
    if filename is None:
        raise ctx.TaskDataError(f"未知文档类型 {doc!r}（仅 spec/task）")
    directory = tasks[tid].get("dir", "")
    root = base.resolve()
    path = (root / directory / filename).resolve()
    if not any(path.is_relative_to(allowed) for allowed in _allowed_doc_roots(root)):
        raise ctx.TaskDataError(f"任务 {tid} 文档路径越界：{path}")
    if not path.is_file():
        raise ctx.TaskDataError(f"任务 {tid} 无 {filename}")
    return path


def _resolve_task_doc(tasks: dict[str, dict], tid: str, doc: str) -> Path:
    """主仓内解析任务文档路径；非法请求抛 ctx.TaskDataError。"""
    return _resolve_task_doc_in(ctx.REPO_ROOT, tasks, tid, doc)


def _read_task_doc(schedule: dict, sources: dict, tid: str, doc: str) -> bytes:
    """按有效状态来源读取任务文档：worktree 读该 worktree 文件、branch 用 git show、main 读主仓。

    task 状态权威在其 worktree/未合并分支：主仓副本可能是过期 backlog，归档路径甚至不存在。
    """
    tasks = schedule["tasks"]
    entry = sources.get(tid) or {}
    if entry.get("source") == "branch" and entry.get("read_at"):
        if tid not in tasks:
            raise ctx.TaskDataError(f"未知任务 {tid!r}")
        filename = _DOC_NAMES.get(doc)
        if filename is None:
            raise ctx.TaskDataError(f"未知文档类型 {doc!r}（仅 spec/task）")
        rel = f"{tasks[tid].get('dir', '')}/{filename}"
        return git_text_at_ref(entry["read_at"], rel).encode("utf-8")
    base = (
        Path(entry["read_at"])
        if entry.get("source") == "worktree" and entry.get("read_at")
        else ctx.REPO_ROOT
    )
    return _resolve_task_doc_in(base, tasks, tid, doc).read_bytes()


def _is_wsl() -> bool:
    """检测是否在 WSL 内运行（与 open-in-software skill 同口径）。"""
    if os.environ.get("WSL_INTEROP") or os.environ.get("WSL_DISTRO_NAME"):
        return True
    try:
        version = Path("/proc/version").read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    lower = version.lower()
    return "microsoft" in lower or "wsl" in lower


def _is_windows() -> bool:
    """原生 Windows 或 Git Bash / MSYS / Cygwin。"""
    if os.name == "nt":
        return True
    system = platform.system().upper()
    return system.startswith(("MINGW", "MSYS", "CYGWIN"))


def _open_browser_windows(url: str) -> bool:
    """用 Windows 默认浏览器打开 URL。成功返回 True。"""
    # PowerShell Start-Process：WSL / Git Bash 均可用；经环境变量传 URL 避免引号问题。
    for pwsh in (
        "pwsh.exe",
        "powershell.exe",
        "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe",
    ):
        try:
            env = os.environ.copy()
            env["TASK_VIEW_OPEN_URL"] = url
            if _is_wsl():
                existing = env.get("WSLENV", "")
                env["WSLENV"] = (existing + ":" if existing else "") + "TASK_VIEW_OPEN_URL"
            result = subprocess.run(
                [
                    pwsh,
                    "-NoProfile",
                    "-Command",
                    "Start-Process -FilePath $env:TASK_VIEW_OPEN_URL",
                ],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
                env=env,
            )
            if result.returncode == 0:
                return True
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            continue
    # 兜底：cmd start；空标题避免 URL 被当成窗口标题。
    try:
        result = subprocess.run(
            ["cmd.exe", "/c", "start", "", url],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


def _open_browser(url: str) -> None:
    """打开默认浏览器：WSL → Windows 浏览器；Windows 直接开；其它 webbrowser。"""
    if _is_wsl():
        if _open_browser_windows(url):
            return
    elif _is_windows():
        startfile = getattr(os, "startfile", None)
        if callable(startfile):
            try:
                startfile(url)
                return
            except OSError:
                pass
        if _open_browser_windows(url):
            return
    try:
        webbrowser.open(url)
    except Exception:
        pass


def _log_error_detail(context: str, error: BaseException):
    """A61: 异常详情只记内部 stderr，对外响应一律固定文案，
    避免回显异常原文与绝对路径。"""
    print(f"view_server: {context}：{error}", file=sys.stderr)


_LOOPBACK_HOSTNAMES = {"127.0.0.1", "localhost", "::1"}


def _split_host_port(value: str) -> tuple[str, int | None]:
    """解析 Host/Origin 的 netloc → (hostname, port)；解析失败返回 ("", None)。"""
    try:
        parts = urlsplit(f"//{value.strip()}")
        return (parts.hostname or "").lower(), parts.port
    except ValueError:
        return "", None


def _server_address(handler) -> tuple | None:
    server = getattr(handler, "server", None)
    address = getattr(server, "server_address", None)
    return address if isinstance(address, tuple) and len(address) >= 2 else None


def _request_host_allowed(handler) -> bool:
    """A29: Host 必须是 loopback 名 + 服务器实际端口，防 DNS rebinding
    用外部域名把浏览器请求重绑到本机看板。显式 --allow-non-loopback
    绑定（通配或指定 LAN 地址）是用户已确认的暴露面，按绑定地址放行。"""
    headers = getattr(handler, "headers", None)
    host = headers.get("Host") if headers is not None else None
    if not host:
        return False
    hostname, port = _split_host_port(host)
    if not hostname:
        return False
    address = _server_address(handler)
    if address is not None and port != address[1]:
        return False
    if hostname in _LOOPBACK_HOSTNAMES:
        return True
    if address is not None:
        bind = str(address[0]).lower()
        if bind in ("0.0.0.0", "::") or hostname == bind:
            return True
    return False


def _request_origin_allowed(handler) -> bool:
    """A29: 带 Origin 的请求必须是同源（与 Host 完全一致），拒绝跨站发起。"""
    headers = getattr(handler, "headers", None)
    if headers is None:
        return True
    origin = headers.get("Origin")
    if not origin:
        return True
    try:
        parts = urlsplit(origin)
    except ValueError:
        return False
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return False
    host = headers.get("Host") or ""
    host_name, host_port = _split_host_port(host)
    try:
        origin_port = parts.port
    except ValueError:
        return False
    return parts.hostname.lower() == host_name and origin_port == host_port


def _request_allowed(handler) -> bool:
    """请求级门禁。headers 缺失只出现在直接构造假 handler 的单测里，
    真实请求经 http.server 解析后必有 headers，此时严格校验。"""
    if getattr(handler, "headers", None) is None:
        return True
    return _request_host_allowed(handler) and _request_origin_allowed(handler)


def _expected_doc_token(handler) -> str | None:
    server = getattr(handler, "server", None)
    token = getattr(server, "doc_token", None)
    return token if token else _DOC_TOKEN


class _Handler(BaseHTTPRequestHandler):
    # A259: 单连接请求超时（秒）。ThreadingHTTPServer 无内建超时，慢/半截
    # 请求会无限期占住线程；StreamRequestHandler.setup 依据此值 settimeout。
    timeout = 30

    def _send_bytes(self, status: int, body: bytes, content_type: str):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        # A61: 全响应安全头，防 MIME 嗅探与外部资源加载
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'")
        self.end_headers()
        self.wfile.write(body)

    def _send_error_text(self, status: int, message: str):
        self._send_bytes(
            status, message.encode("utf-8"), "text/plain; charset=utf-8"
        )

    def do_GET(self):
        """请求级兜底：SystemExit（如非主工作区运行）与意外异常转明确文本响应。

        http.server 对线程内未捕获异常只打 traceback 并关连接，客户端得到空响应。
        """
        try:
            if not _request_allowed(self):
                self._send_error_text(403, "请求被拒绝")
                return
            self._route_get()
        except SystemExit as error:
            self._send_error_text(503, str(error) or "服务不可用（运行环境不满足）")
        except Exception as error:  # noqa: BLE001 - 请求级兜底，保证有明确错误响应
            _log_error_detail("未捕获异常", error)
            self._send_error_text(500, "内部错误")

    def _route_get(self):
        parts = urlsplit(self.path)
        path = parts.path
        if path in ("/", "/index.html"):
            try:
                html = _render_html(_build_model())
            except Exception as e:
                _log_error_detail("渲染失败", e)
                self._send_error_text(500, "渲染失败")
                return
            self._send_bytes(200, html.encode("utf-8"), "text/html; charset=utf-8")
            return
        if path.startswith("/static/"):
            name = path[len("/static/"):]
            if name not in ("board.css", "board.js", "chain_plan.js"):
                self._send_error_text(404, "静态资源不存在")
                return
            try:
                body = (_STATIC_DIR / name).read_bytes()
            except OSError as e:
                _log_error_detail("读取静态资源失败", e)
                self._send_error_text(500, "读取静态资源失败")
                return
            content_type = (
                "text/css; charset=utf-8" if name.endswith(".css")
                else "text/javascript; charset=utf-8"
            )
            self._send_bytes(200, body, content_type)
            return
        if path == "/task-doc":
            query = parse_qs(parts.query)
            # A29: 正文接口须携带 serve 启动时生成的一次性 token
            expected_token = _expected_doc_token(self)
            provided_token = (query.get("token") or [""])[0]
            if expected_token and not secrets.compare_digest(
                provided_token, expected_token
            ):
                self._send_error_text(403, "请求被拒绝")
                return
            tid = (query.get("tid") or [""])[0]
            doc = (query.get("doc") or [""])[0]
            try:
                body = _read_task_doc(
                    compute_schedule(), discover_effective_sources(), tid, doc
                )
            except ctx.TaskDataError as e:
                # TaskDataError 文案可能含越界文档的绝对路径，一律固定文案对外
                _log_error_detail("任务文档不可用", e)
                self._send_error_text(404, "任务文档不存在或不可用")
                return
            except OSError as e:
                _log_error_detail("读取文档失败", e)
                self._send_error_text(500, "读取文档失败")
                return
            self._send_bytes(200, body, "text/plain; charset=utf-8")
            return
        self._send_error_text(404, "未找到资源")

    def log_message(self, *args):
        pass


def _is_loopback_host(host: str) -> bool:
    """本机回环地址才视为默认安全绑定。"""
    normalized = (host or "").strip().lower()
    return normalized in {"127.0.0.1", "localhost", "::1", "0:0:0:0:0:0:0:1"}


def serve(host="127.0.0.1", port=0, *, allow_non_loopback=False):
    global _DOC_TOKEN
    # A29: 每次启动生成一次性 token，经看板页面注入、/task-doc 校验
    _DOC_TOKEN = secrets.token_urlsafe(32)
    if not _is_loopback_host(host):
        if not allow_non_loopback:
            sys.exit(
                f"看板拒绝绑定非 loopback 主机 {host!r}"
                "（只读但暴露 task spec/task 正文）；确认网络边界后加"
                " --allow-non-loopback，或改用默认 127.0.0.1"
            )
        print(
            f"WARNING: 看板绑定 {host!r}（非 loopback）；"
            "只读但会暴露 task spec/task 正文，确认网络边界后再用",
            file=sys.stderr,
        )
    bind_host = host[1:-1] if host.startswith("[") and host.endswith("]") else host
    try:
        # port=0 时由 OS 在构造时直接分配空闲端口，不做探活-释放-重绑，
        # 消除 _find_free_port 式的 TOCTOU 窗口；实际端口从 server_address 读。
        httpd = _server_class_for_host(bind_host)((bind_host, port), _Handler)
    except OSError as error:
        sys.exit(f"看板端口 {port} 绑定失败（{error}）；改用 --port 0 自动选空闲端口")
    httpd.doc_token = _DOC_TOKEN
    actual_port = httpd.server_address[1]
    # ThreadingHTTPServer 对 IPv6 字面量需要方括号才能当 URL host
    url_host = f"[{host}]" if ":" in host and not host.startswith("[") else host
    url = f"http://{url_host}:{actual_port}/"
    print(f"task 看板已启动：{url}")
    print("只读服务；Ctrl+C 退出。")
    _open_browser(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n关闭。")
        httpd.shutdown()
    finally:
        httpd.server_close()
