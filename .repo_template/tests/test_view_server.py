"""task 看板 view_server 纯函数测试。"""
import socket
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import repo_task.context as ctx
from repo_task import view_server

pytestmark = pytest.mark.contract


def test_classify_maps_categories():
    tasks = {
        "t001": {"status": "active"},
        "t002": {"status": "done"},
        "t003": {"status": "dropped"},
        "t004": {"status": "backlog"},
        "t005": {"status": "backlog"},
        "t006": {"status": "backlog"},
        "t007": {"status": "backlog"},
    }
    schedule = {
        "selected": ["t004"],
        "waiting_deps": [("t001", "t005")],
        "blocked_conflicts": [("t006", "t001")],
    }
    classify = view_server.classify_node
    assert classify("t001", tasks, schedule) == "active"
    assert classify("t002", tasks, schedule) == "done"
    assert classify("t003", tasks, schedule) == "dropped"
    assert classify("t004", tasks, schedule) == "runnable"
    assert classify("t005", tasks, schedule) == "blocked_deps"
    assert classify("t006", tasks, schedule) == "blocked_conflict"
    assert classify("t007", tasks, schedule) == "backlog"


def test_render_html_injects_model_json(tmp_path, monkeypatch):
    # 隔离 view_static 读取：用真实模板，仅替换注入内容断言转义行为
    model = {
        "project": "demo",
        "nodes": [{"id": "t001", "title": "</script><b>x</b>", "category": "runnable"}],
        "edges": [],
        "summary": {"active": 0, "runnable": 1},
    }
    html = view_server._render_html(model)
    assert "window.__BOARD__ =" in html
    assert "</script><b>x</b>" not in html  # 防止注入闭合 script 标签
    assert "<\\/script>" in html
    assert "/static/board.css" in html
    assert "/static/board.js" in html


def test_render_html_uses_existing_template():
    template = Path(__file__).resolve().parents[1] / "scripts" / "repo_task" / "view_static" / "board.html"
    assert template.is_file()
    text = template.read_text(encoding="utf-8")
    assert "__BOARD_JSON__" in text


@pytest.fixture()
def repo_layout(tmp_path, monkeypatch):
    tasks_dir = tmp_path / "docs" / "tasks"
    archive_dir = tmp_path / "docs" / "archive" / "tasks"
    tasks_dir.mkdir(parents=True)
    archive_dir.mkdir(parents=True)
    (tasks_dir / "t001_spec_doc").mkdir()
    (tasks_dir / "t001_spec_doc" / "spec.md").write_text("# spec 正文\n", encoding="utf-8")
    (tasks_dir / "t001_spec_doc" / "task.md").write_text("# task 正文\n", encoding="utf-8")
    (archive_dir / "t002_archived").mkdir()
    (archive_dir / "t002_archived" / "spec.md").write_text("# 归档 spec\n", encoding="utf-8")
    monkeypatch.setattr(ctx, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(ctx, "TASKS_DIR", tasks_dir)
    monkeypatch.setattr(ctx, "ARCHIVE_TASKS_DIR", archive_dir)
    return tasks_dir, archive_dir


def test_resolve_task_doc_ok(repo_layout):
    tasks = {"t001": {"dir": "docs/tasks/t001_spec_doc"}}
    path = view_server._resolve_task_doc(tasks, "t001", "spec")
    assert path.read_text(encoding="utf-8") == "# spec 正文\n"
    assert view_server._resolve_task_doc(tasks, "t001", "task").name == "task.md"


def test_resolve_task_doc_archived_ok(repo_layout):
    tasks = {"t002": {"dir": "docs/archive/tasks/t002_archived"}}
    path = view_server._resolve_task_doc(tasks, "t002", "spec")
    assert path.read_text(encoding="utf-8") == "# 归档 spec\n"


def test_resolve_task_doc_rejects_unknown_tid(repo_layout):
    with pytest.raises(ctx.TaskDataError):
        view_server._resolve_task_doc({}, "t999", "spec")


def test_resolve_task_doc_rejects_bad_doc(repo_layout):
    tasks = {"t001": {"dir": "docs/tasks/t001_spec_doc"}}
    with pytest.raises(ctx.TaskDataError):
        view_server._resolve_task_doc(tasks, "t001", "readme")


def test_resolve_task_doc_rejects_missing_file(repo_layout):
    # 目录存在但文件缺失
    tasks_dir = repo_layout[0]
    (tasks_dir / "t003_missing").mkdir()
    tasks3 = {"t003": {"dir": "docs/tasks/t003_missing"}}
    with pytest.raises(ctx.TaskDataError):
        view_server._resolve_task_doc(tasks3, "t003", "spec")


def test_resolve_task_doc_rejects_path_traversal(repo_layout):
    tasks = {"t001": {"dir": "../../../etc"}}
    with pytest.raises(ctx.TaskDataError):
        view_server._resolve_task_doc(tasks, "t001", "spec")


def test_read_task_doc_from_worktree_source(tmp_path):
    """worktree 来源任务：读该 worktree 的文件，而非主仓过期副本。"""
    main = tmp_path / "main"
    (main / "docs/tasks/t001_x").mkdir(parents=True)
    (main / "docs/tasks/t001_x/spec.md").write_text("# 主仓旧版\n", encoding="utf-8")
    worktree = tmp_path / "main_t001"
    (worktree / "docs/tasks/t001_x").mkdir(parents=True)
    (worktree / "docs/tasks/t001_x/spec.md").write_text("# worktree 最新\n", encoding="utf-8")

    schedule = {"tasks": {"t001": {"dir": "docs/tasks/t001_x"}}}
    sources = {"t001": {"source": "worktree", "read_at": str(worktree)}}
    body = view_server._read_task_doc(schedule, sources, "t001", "spec")
    assert body.decode("utf-8") == "# worktree 最新\n"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True,
        encoding="utf-8", errors="replace", check=True,
    )


def test_read_task_doc_from_branch_source(tmp_path, monkeypatch):
    """branch 来源（done 未合并）：用 git show 读分支归档文档，不落主仓 404。"""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "t@e.c")
    _git(repo, "config", "user.name", "t")
    (repo / "base.txt").write_text("x\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "init")
    _git(repo, "checkout", "-b", "t001_x")
    (repo / "docs/archive/tasks/t001_x").mkdir(parents=True)
    (repo / "docs/archive/tasks/t001_x/task.md").write_text("# 分支归档 task\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "task")
    _git(repo, "checkout", "main")

    monkeypatch.setattr(ctx, "REPO_ROOT", repo)
    schedule = {"tasks": {"t001": {"dir": "docs/archive/tasks/t001_x"}}}
    sources = {"t001": {"source": "branch", "read_at": "t001_x"}}
    body = view_server._read_task_doc(schedule, sources, "t001", "task")
    assert body.decode("utf-8") == "# 分支归档 task\n"
    with pytest.raises(ctx.TaskDataError):
        view_server._read_task_doc(schedule, sources, "t001", "spec")


def test_handler_maps_system_exit_to_error_response():
    """请求线程 SystemExit（worktree 运行）不再空响应：503 + 明确文本。"""

    class FakeHandler:
        path = "/"

        def _route_get(self):
            raise SystemExit("此命令只能在主工作区执行；请 cd 回主仓")

        def _send_error_text(self, status, message):
            self.result = (status, message)

    handler = FakeHandler()
    view_server._Handler.do_GET(handler)
    assert handler.result == (503, "此命令只能在主工作区执行；请 cd 回主仓")


def test_handler_maps_unexpected_exception_to_500(capsys):
    # REPLACED (A61): 旧预期 (500, "内部错误：boom") 把异常原文回显给客户端，
    # 正是本条目要修的泄漏；新语义为对外固定文案、详情只记 stderr。
    class FakeHandler:
        path = "/task-doc?tid=t001&doc=task"

        def _route_get(self):
            raise ValueError("boom")

        def _send_error_text(self, status, message):
            self.result = (status, message)

    handler = FakeHandler()
    view_server._Handler.do_GET(handler)
    assert handler.result == (500, "内部错误")
    assert "boom" in capsys.readouterr().err


def test_send_bytes_adds_security_headers():
    # A61: 全响应须带 nosniff 与 CSP 头。
    import io

    class FakeHandler:
        def __init__(self):
            self.headers = {}
            self.wfile = io.BytesIO()

        def send_response(self, status):
            self.status = status

        def send_header(self, key, value):
            self.headers[key] = value

        def end_headers(self):
            pass

    handler = FakeHandler()
    view_server._Handler._send_bytes(handler, 200, b"hi", "text/plain")
    assert handler.headers["X-Content-Type-Options"] == "nosniff"
    assert handler.headers["Content-Security-Policy"] == "default-src 'self'"
    assert handler.wfile.getvalue() == b"hi"


def _route_fake(path):
    class FakeHandler:
        def __init__(self):
            self.path = path

        def _send_error_text(self, status, message):
            self.result = (status, message)

        def _send_bytes(self, status, body, content_type):
            self.result = (status, body)

    return FakeHandler()


def test_route_render_error_is_fixed_text_without_exception_detail(monkeypatch, capsys):
    handler = _route_fake("/")

    def boom():
        raise ValueError("/home/alice/secret 渲染炸了")

    monkeypatch.setattr(view_server, "_build_model", boom)
    view_server._Handler._route_get(handler)
    status, message = handler.result
    assert status == 500
    assert "/home/alice" not in message and "渲染炸了" not in message
    assert "/home/alice" in capsys.readouterr().err  # 详情只进内部日志


def test_route_task_doc_error_does_not_leak_absolute_path(monkeypatch, capsys):
    monkeypatch.setattr(view_server, "_DOC_TOKEN", "tok-a61")
    handler = _route_fake("/task-doc?tid=t001&doc=spec&token=tok-a61")
    monkeypatch.setattr(view_server, "compute_schedule", lambda: {"tasks": {}})
    monkeypatch.setattr(view_server, "discover_effective_sources", lambda: {})

    def leak(*args):
        raise ctx.TaskDataError("任务 t001 文档路径越界：/home/alice/secret/spec.md")

    monkeypatch.setattr(view_server, "_read_task_doc", leak)
    view_server._Handler._route_get(handler)
    status, message = handler.result
    assert status == 404
    assert "/home/alice" not in message
    assert "/home/alice" in capsys.readouterr().err


def test_route_static_read_error_is_fixed_text(monkeypatch, capsys, tmp_path):
    handler = _route_fake("/static/board.css")
    monkeypatch.setattr(view_server, "_STATIC_DIR", tmp_path)  # 空目录 → OSError
    view_server._Handler._route_get(handler)
    status, message = handler.result
    assert status == 500
    assert str(tmp_path) not in message
    assert str(tmp_path) in capsys.readouterr().err




def test_is_wsl_detects_env(monkeypatch):
    monkeypatch.setenv("WSL_DISTRO_NAME", "Ubuntu")
    assert view_server._is_wsl() is True


def test_is_wsl_detects_proc_version(monkeypatch):
    monkeypatch.delenv("WSL_DISTRO_NAME", raising=False)
    monkeypatch.delenv("WSL_INTEROP", raising=False)

    class FakePath:
        def __init__(self, path):
            self._path = str(path)

        def read_text(self, encoding="utf-8", errors="ignore"):
            assert self._path == "/proc/version"
            return "Linux version 5.15.0-microsoft-standard-WSL2"

    monkeypatch.setattr(view_server, "Path", FakePath)
    assert view_server._is_wsl() is True


def test_open_browser_wsl_uses_windows_default(monkeypatch):
    calls = []

    def fake_windows(url):
        calls.append(url)
        return True

    monkeypatch.setattr(view_server, "_is_wsl", lambda: True)
    monkeypatch.setattr(view_server, "_is_windows", lambda: False)
    monkeypatch.setattr(view_server, "_open_browser_windows", fake_windows)
    opened = []
    monkeypatch.setattr(view_server.webbrowser, "open", lambda url: opened.append(url))
    view_server._open_browser("http://127.0.0.1:1234/")
    assert calls == ["http://127.0.0.1:1234/"]
    assert opened == []


def test_open_browser_windows_nt_uses_startfile(monkeypatch):
    started = []
    monkeypatch.setattr(view_server, "_is_wsl", lambda: False)
    monkeypatch.setattr(view_server, "_is_windows", lambda: True)
    monkeypatch.setattr(
        view_server.os, "startfile", lambda url: started.append(url), raising=False
    )
    win_calls = []
    monkeypatch.setattr(
        view_server, "_open_browser_windows", lambda url: win_calls.append(url) or True
    )
    opened = []
    monkeypatch.setattr(view_server.webbrowser, "open", lambda url: opened.append(url))
    view_server._open_browser("http://127.0.0.1:9/")
    assert started == ["http://127.0.0.1:9/"]
    assert win_calls == []
    assert opened == []


def test_open_browser_other_uses_webbrowser(monkeypatch):
    monkeypatch.setattr(view_server, "_is_wsl", lambda: False)
    monkeypatch.setattr(view_server, "_is_windows", lambda: False)
    opened = []
    monkeypatch.setattr(view_server.webbrowser, "open", lambda url: opened.append(url))
    view_server._open_browser("http://127.0.0.1:9/")
    assert opened == ["http://127.0.0.1:9/"]


def test_is_loopback_host():
    assert view_server._is_loopback_host("127.0.0.1")
    assert view_server._is_loopback_host("localhost")
    assert view_server._is_loopback_host("::1")
    assert not view_server._is_loopback_host("0.0.0.0")
    assert not view_server._is_loopback_host("192.168.1.1")


def test_server_class_for_host_matches_address_family():
    # A207: _is_loopback_host 认可 ::1，服务器类必须同步支持 AF_INET6，
    # 否则 serve(host="::1") 必然绑定失败。
    assert view_server._server_class_for_host("127.0.0.1").address_family == socket.AF_INET
    assert view_server._server_class_for_host("localhost").address_family == socket.AF_INET
    assert view_server._server_class_for_host("::1").address_family == socket.AF_INET6
    assert view_server._server_class_for_host("[::1]").address_family == socket.AF_INET6


def test_ipv6_loopback_server_actually_binds():
    server_cls = view_server._server_class_for_host("::1")
    try:
        httpd = server_cls(("::1", 0), view_server._Handler)
    except OSError as error:  # 环境无 IPv6 时跳过不断言
        pytest.skip(f"IPv6 不可用：{error}")
    try:
        assert httpd.server_address[0] == "::1"
        assert httpd.server_address[1] > 0
    finally:
        httpd.server_close()


def test_serve_warns_non_loopback(monkeypatch, capsys):
    class FakeServer:
        def __init__(self, addr, handler):
            self.addr = addr
            self.server_address = addr

        def serve_forever(self):
            raise KeyboardInterrupt

        def shutdown(self):
            pass

        def server_close(self):
            pass

    monkeypatch.setattr(view_server, "ThreadingHTTPServer", FakeServer)
    monkeypatch.setattr(view_server, "_open_browser", lambda url: None)
    # RT-013 后非 loopback 须显式 allow_non_loopback 才绑定；绑定后仍打 WARNING
    view_server.serve(host="0.0.0.0", port=8765, allow_non_loopback=True)
    err = capsys.readouterr().err
    assert "WARNING" in err
    assert "0.0.0.0" in err


def test_serve_rejects_non_loopback_without_allow(monkeypatch, capsys):
    """非 loopback 绑定需显式 --allow-non-loopback，否则拒绝（RT-013）。"""
    class FakeServer:
        def __init__(self, addr, handler):
            self.addr = addr
            self.server_address = addr

        def serve_forever(self):
            raise KeyboardInterrupt

        def shutdown(self):
            pass

        def server_close(self):
            pass

    monkeypatch.setattr(view_server, "ThreadingHTTPServer", FakeServer)
    monkeypatch.setattr(view_server, "_open_browser", lambda url: None)
    with pytest.raises(SystemExit, match="拒绝绑定非 loopback"):
        view_server.serve(host="0.0.0.0", port=8766)


def test_serve_uses_os_assigned_port_and_closes_server(monkeypatch):
    """A223: port=0 直接构造服务器、从 server_address 读实际端口拼 URL，
    不再探活-释放-重绑（TOCTOU）；退出路径必须 server_close。"""
    events = []

    class FakeServer:
        def __init__(self, addr, handler):
            self.addr = addr
            # 模拟 OS 分配端口：与请求端口不同，URL 必须以此为准
            self.server_address = (addr[0], 49152)

        def serve_forever(self):
            raise KeyboardInterrupt

        def shutdown(self):
            events.append("shutdown")

        def server_close(self):
            events.append("server_close")

    monkeypatch.setattr(view_server, "ThreadingHTTPServer", FakeServer)
    opened = []
    monkeypatch.setattr(view_server, "_open_browser", lambda url: opened.append(url))
    view_server.serve(host="127.0.0.1", port=0)
    assert opened == ["http://127.0.0.1:49152/"]
    assert "server_close" in events
    # 探活-释放-重绑的旧 helper 已移除，serve 不应再依赖它
    assert not hasattr(view_server, "_find_free_port")


def _headers_fake(host=None, origin=None, server_address=("127.0.0.1", 8765)):
    """构造带 headers/server 的假 handler，供 A29 Host/Origin 校验测试。"""
    from email.message import Message
    from types import SimpleNamespace

    headers = Message()
    if host is not None:
        headers["Host"] = host
    if origin is not None:
        headers["Origin"] = origin
    return SimpleNamespace(
        headers=headers,
        server=SimpleNamespace(server_address=server_address),
    )


def test_request_host_must_be_loopback_with_actual_port():
    # A29: DNS rebinding 用外部域名 Host 访问本机端口必须被拒
    assert view_server._request_host_allowed(_headers_fake("127.0.0.1:8765"))
    assert view_server._request_host_allowed(_headers_fake("localhost:8765"))
    assert view_server._request_host_allowed(_headers_fake("[::1]:8765"))
    assert not view_server._request_host_allowed(_headers_fake("evil.example.com:8765"))
    assert not view_server._request_host_allowed(_headers_fake("127.0.0.1:9999"))  # 端口不符
    assert not view_server._request_host_allowed(_headers_fake("127.0.0.1"))  # 缺端口
    assert not view_server._request_host_allowed(_headers_fake(None))


def test_request_origin_must_match_host_when_present():
    assert view_server._request_origin_allowed(
        _headers_fake("127.0.0.1:8765", "http://127.0.0.1:8765")
    )
    assert view_server._request_origin_allowed(_headers_fake("127.0.0.1:8765", None))
    assert not view_server._request_origin_allowed(
        _headers_fake("127.0.0.1:8765", "http://evil.example.com")
    )
    assert not view_server._request_origin_allowed(
        _headers_fake("127.0.0.1:8765", "http://127.0.0.1:9999")
    )


def test_do_get_rejects_disallowed_host_before_routing():
    routed = []

    class FakeHandler:
        headers = _headers_fake("evil.example.com:8765").headers
        server = _headers_fake("evil.example.com:8765").server
        path = "/"

        def _route_get(self):
            routed.append(True)

        def _send_error_text(self, status, message):
            self.result = (status, message)

    handler = FakeHandler()
    view_server._Handler.do_GET(handler)
    assert handler.result[0] == 403
    assert routed == []


def test_task_doc_requires_valid_token(monkeypatch):
    monkeypatch.setattr(view_server, "_DOC_TOKEN", "s3cret-token")
    monkeypatch.setattr(view_server, "compute_schedule", lambda: {"tasks": {}})
    monkeypatch.setattr(view_server, "discover_effective_sources", lambda: {})
    monkeypatch.setattr(
        view_server, "_read_task_doc", lambda *args: b"# doc body"
    )

    no_token = _route_fake("/task-doc?tid=t001&doc=spec")
    view_server._Handler._route_get(no_token)
    assert no_token.result[0] == 403

    wrong = _route_fake("/task-doc?tid=t001&doc=spec&token=wrong")
    view_server._Handler._route_get(wrong)
    assert wrong.result[0] == 403

    ok = _route_fake("/task-doc?tid=t001&doc=spec&token=s3cret-token")
    view_server._Handler._route_get(ok)
    assert ok.result == (200, b"# doc body")


def test_render_html_injects_doc_token_and_board_js_sends_it(monkeypatch):
    monkeypatch.setattr(view_server, "_DOC_TOKEN", "tok-abc")
    model = {"project": "demo", "nodes": [], "edges": [], "summary": {}}
    html = view_server._render_html(model)
    assert 'window.__DOC_TOKEN__ = "tok-abc"' in html
    assert "__DOC_TOKEN_JSON__" not in html  # 占位符已全部替换
    board_js = (
        Path(__file__).resolve().parents[1]
        / "scripts" / "repo_task" / "view_static" / "board.js"
    ).read_text(encoding="utf-8")
    assert "__DOC_TOKEN__" in board_js and "token=" in board_js


def test_serve_generates_doc_token(monkeypatch):
    servers = []

    class FakeServer:
        def __init__(self, addr, handler):
            self.server_address = addr
            servers.append(self)

        def serve_forever(self):
            raise KeyboardInterrupt

        def shutdown(self):
            pass

        def server_close(self):
            pass

    monkeypatch.setattr(view_server, "ThreadingHTTPServer", FakeServer)
    monkeypatch.setattr(view_server, "_open_browser", lambda url: None)
    monkeypatch.setattr(view_server, "_DOC_TOKEN", None)
    view_server.serve(host="127.0.0.1", port=8765)
    assert isinstance(view_server._DOC_TOKEN, str) and len(view_server._DOC_TOKEN) >= 16
    assert servers[0].doc_token == view_server._DOC_TOKEN


def test_handler_has_request_timeout():
    # A259: ThreadingHTTPServer 本身无连接超时，慢连接可无限期占线程；
    # handler 必须带有限 timeout（StreamRequestHandler.setup 会据此 settimeout）。
    assert view_server._Handler.timeout == 30


def test_handler_timeout_disconnects_slow_client():
    """慢连接（只发半行请求就停住）应在 handler timeout 后被断开。"""
    import threading

    class FastTimeoutHandler(view_server._Handler):
        timeout = 0.3

    httpd = view_server.ThreadingHTTPServer(("127.0.0.1", 0), FastTimeoutHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = httpd.server_address[:2]
        with socket.create_connection((host, port), timeout=5) as sock:
            sock.sendall(b"GET / HTTP/1.1\r\n")  # 半截请求，之后不再发送
            sock.settimeout(5)
            assert sock.recv(1024) == b""  # 超时后服务端关闭连接
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def test_build_model_has_no_schedule_status(monkeypatch):
    schedule = {
        'tasks': {
            't001': {'tid': 't001', 'title': 'one', 'status': 'backlog', 'depends_on': '', 'conflicts_with': 't002'},
            't002': {'tid': 't002', 'title': 'two', 'status': 'backlog', 'depends_on': '', 'conflicts_with': ''},
        },
        'selected': ['t001', 't002'],
        'waiting_deps': [], 'blocked_conflicts': [],
        'conflicts': {'t001': {'t002'}, 't002': {'t001'}},
        'main_done_set': set(), 'effective_done_set': set(), 'unmerged_done': [],
        'dropped_set': set(), 'active_list': [], 'active_set': set(),
        'backlog_tasks': {}, 'ready': ['t001', 't002'],
    }
    monkeypatch.setattr(view_server, 'compute_schedule', lambda: schedule)
    model = view_server._build_model()
    assert {node['id'] for node in model['nodes']} == {'t001', 't002'}
    assert all('schedule_status' not in node for node in model['nodes'])
    assert model['edges'] == [{'type': 'conflict', 'from': 't001', 'to': 't002'}]
