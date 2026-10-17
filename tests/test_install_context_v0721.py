# -*- coding: utf-8 -*-
"""v0.7.21: install-context Win11 锁修法 (try/except per BASE_KEY skip).

老八 v0.7.20 实机复现 100% 失败 (WinError 5 锁 Directory\shell + Directory\Background\shell).
v0.7.21 修法: 单 base_key 抛 PermissionError 时 skip 继续, 至少 1/3 base_key 装成功.
"""
from pandaone import i18n


def test_v0721_ctx_win11_lock_skip_exists_zh():
    """v0.7.21: ctx_win11_lock_skip key 存在 (zh)."""
    zh = i18n.TRANSLATIONS["zh-CN"]
    assert "ctx_win11_lock_skip" in zh
    # 含 Win11 锁提示
    assert "Win11" in zh["ctx_win11_lock_skip"]
    assert "{base}" in zh["ctx_win11_lock_skip"]
    assert "{err}" in zh["ctx_win11_lock_skip"]


def test_v0721_ctx_win11_lock_skip_exists_en():
    """v0.7.21: ctx_win11_lock_skip key 存在 (en)."""
    en = i18n.TRANSLATIONS["en"]
    assert "ctx_win11_lock_skip" in en
    assert "Win11" in en["ctx_win11_lock_skip"]
    assert "{base}" in en["ctx_win11_lock_skip"]
    assert "{err}" in en["ctx_win11_lock_skip"]


def test_v0721_ctx_partial_install_summary_exists():
    """v0.7.21: ctx_partial_install_summary key 存在 (zh + en)."""
    for lang in ("zh-CN", "en"):
        d = i18n.TRANSLATIONS[lang]
        assert "ctx_partial_install_summary" in d, f"missing in {lang}"
        assert "{ok}" in d["ctx_partial_install_summary"]
        assert "{total}" in d["ctx_partial_install_summary"]


def test_v0721_t_renders_win11_lock_skip():
    """v0.7.21: t() 渲染 ctx_win11_lock_skip 含 base + err."""
    i18n._CURRENT_LANG = "zh-CN"
    rendered = i18n.t(
        "ctx_win11_lock_skip",
        base=r"Software\Classes\Directory\shell\Pandaone",
        err="[WinError 5] 拒绝访问",
    )
    assert "Win11" in rendered
    assert "Directory\\shell\\Pandaone" in rendered
    assert "WinError 5" in rendered


def test_v0721_t_renders_partial_install_summary():
    """v0.7.21: t() 渲染 ctx_partial_install_summary 含 ok + total + fail."""
    i18n._CURRENT_LANG = "zh-CN"
    rendered = i18n.t("ctx_partial_install_summary", ok=1, total=3, fail=2)
    assert "1/3" in rendered
    assert "2" in rendered  # fail
