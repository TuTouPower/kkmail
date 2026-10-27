"""board.js 静态源码回归（沿用 test_view_server 对 board.js 的源码断言口径）。

board.js 依赖 DOM/window.__BOARD__，无法在 node 下直接执行；本文件以源码
断言锁定与类别/剪贴板/缓存相关的安全口径，行为细节由人工核查兜底。
"""
import re
from pathlib import Path

BOARD_JS = (
    Path(__file__).resolve().parents[1]
    / "scripts" / "repo_task" / "view_static" / "board.js"
)


def _src() -> str:
    return BOARD_JS.read_text(encoding="utf-8")


def test_a224_no_direct_cat_label_lookup():
    """A224：任何 CAT[动态类别].label 直引都会在未知类别时崩溃，必须清零。

    统一经 catLabel 安全访问器（内部 CAT[cat] || CAT.backlog 兜底）。
    """
    src = _src()
    direct = re.findall(r"CAT\[[^\]]+\]\.label", src)
    assert direct == [], f"仍有 CAT 直引 label：{direct}"


def test_a224_cat_label_accessor_falls_back_to_backlog():
    src = _src()
    assert "function catLabel(cat)" in src
    # 兜底实现：未知类别回退 backlog 元数据（与 catStyle 同口径）
    assert re.search(r"CAT\[cat\] \|\| CAT\.backlog\)\.label", src)
    # 动态类别渲染点全部经 catLabel：详情徽章 / 归档卡 / 关系条目 / 链未分配行
    assert "badge.textContent = catLabel(n.category)" in src
    assert "catLabel(target.category)" in src
    assert src.count("catLabel(n.category)") >= 2
