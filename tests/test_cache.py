"""测试 src.data_layer.cache 缓存行为。"""
from __future__ import annotations

import time
from pathlib import Path

import pandas as pd
import pytest

from src.data_layer import cache as cache_module
from src.data_layer.cache import cached_call, clear_cache


@pytest.fixture(autouse=True)
def _clean_cache(tmp_path, monkeypatch):
    """每个用例前重定向 CACHE_DIR 到临时目录，避免污染项目 data/cache/。"""
    fake_cache = tmp_path / "cache"
    monkeypatch.setattr("src.data_layer.cache.CACHE_DIR", fake_cache)
    yield
    # 用例后清理
    if fake_cache.exists():
        for f in fake_cache.glob("*.parquet"):
            f.unlink()


def _df_factory(value: int) -> pd.DataFrame:
    return pd.DataFrame({"v": [value]})


class TestCachedCall:
    def test_first_call_invokes_fetcher(self):
        calls = {"n": 0}

        def fetcher():
            calls["n"] += 1
            return _df_factory(1)

        df = cached_call("test.source", {"k": "v"}, fetcher, ttl_hours=24)
        assert calls["n"] == 1
        assert df["v"].iloc[0] == 1

    def test_second_call_within_ttl_uses_cache(self):
        calls = {"n": 0}

        def fetcher():
            calls["n"] += 1
            return _df_factory(calls["n"])

        cached_call("test.source", {"k": "v"}, fetcher, ttl_hours=24)
        df2 = cached_call("test.source", {"k": "v"}, fetcher, ttl_hours=24)
        assert calls["n"] == 1
        assert df2["v"].iloc[0] == 1  # 缓存值,不是第二次 fetcher 的 2

    def test_force_refresh_bypasses_cache(self):
        calls = {"n": 0}

        def fetcher():
            calls["n"] += 1
            return _df_factory(calls["n"])

        cached_call("test.source", {"k": "v"}, fetcher, ttl_hours=24)
        df2 = cached_call("test.source", {"k": "v"}, fetcher, ttl_hours=24, force=True)
        assert calls["n"] == 2
        assert df2["v"].iloc[0] == 2

    def test_ttl_expired_reinvokes_fetcher(self):
        calls = {"n": 0}

        def fetcher():
            calls["n"] += 1
            return _df_factory(calls["n"])

        cached_call("test.source", {"k": "v"}, fetcher, ttl_hours=0)  # 立即过期
        time.sleep(0.01)
        cached_call("test.source", {"k": "v"}, fetcher, ttl_hours=0)
        assert calls["n"] == 2

    def test_different_params_different_cache(self):
        calls = {"n": 0}

        def fetcher_for_a():
            calls["n"] += 1
            return _df_factory(calls["n"])

        def fetcher_for_b():
            calls["n"] += 1
            return _df_factory(calls["n"])

        cached_call("test.source", {"k": "a"}, fetcher_for_a, ttl_hours=24)
        cached_call("test.source", {"k": "b"}, fetcher_for_b, ttl_hours=24)
        assert calls["n"] == 2

    def test_different_source_same_params_different_cache(self):
        """AKShare 和 westock 拉同一 (k=v) 不能互相覆盖。"""
        a_calls = {"n": 0}
        b_calls = {"n": 0}

        def f_a():
            a_calls["n"] += 1
            return _df_factory(1)

        def f_b():
            b_calls["n"] += 1
            return _df_factory(2)

        df_a = cached_call("akshare.lhb", {"k": "v"}, f_a, ttl_hours=24, force=True)
        df_b = cached_call("westock.lhb", {"k": "v"}, f_b, ttl_hours=24, force=True)
        assert df_a["v"].iloc[0] == 1
        assert df_b["v"].iloc[0] == 2
        # 两个源各调一次
        assert a_calls["n"] == 1
        assert b_calls["n"] == 1


class TestClearCache:
    def test_clear_specific_source(self):
        cached_call("src.a", {"x": 1}, lambda: _df_factory(1), ttl_hours=24)
        cached_call("src.b", {"x": 1}, lambda: _df_factory(2), ttl_hours=24)
        n = clear_cache("src.a")
        assert n == 1
        # src.b 仍在
        assert cache_module.CACHE_DIR.exists()
        files = list(cache_module.CACHE_DIR.glob("*.parquet"))
        assert len(files) == 1
        assert "src.b" in files[0].name

    def test_clear_all(self):
        cached_call("src.a", {"x": 1}, lambda: _df_factory(1), ttl_hours=24)
        cached_call("src.b", {"x": 1}, lambda: _df_factory(2), ttl_hours=24)
        n = clear_cache()
        assert n == 2
        assert not list(cache_module.CACHE_DIR.glob("*.parquet"))
