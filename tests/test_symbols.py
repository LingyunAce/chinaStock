"""测试 src.data_layer.symbols 转换逻辑。"""

from __future__ import annotations

import pytest

from src.data_layer.symbols import to_akshare, to_bare, to_chinastock, to_westock


class TestToBare:
    def test_uppercase_prefix(self):
        assert to_bare("SH600519") == "600519"

    def test_lowercase_prefix(self):
        assert to_bare("sh600519") == "600519"

    def test_no_prefix(self):
        assert to_bare("600519") == "600519"

    def test_sz(self):
        assert to_bare("SZ000001") == "000001"

    def test_bj(self):
        assert to_bare("BJ830799") == "830799"

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            to_bare("")


class TestToChinastock:
    def test_lowercase_to_uppercase(self):
        assert to_chinastock("sh600519") == "SH600519"

    def test_uppercase_passthrough(self):
        assert to_chinastock("SH600519") == "SH600519"

    def test_no_prefix_sh(self):
        assert to_chinastock("600519") == "SH600519"

    def test_no_prefix_sz(self):
        assert to_chinastock("000001") == "SZ000001"

    def test_no_prefix_sz_300(self):
        assert to_chinastock("300750") == "SZ300750"

    def test_no_prefix_bj(self):
        assert to_chinastock("830799") == "BJ830799"

    def test_no_prefix_bj_4(self):
        assert to_chinastock("430047") == "BJ430047"

    def test_no_prefix_9_is_sh(self):
        assert to_chinastock("900901") == "SH900901"

    def test_invalid_first_digit_raises(self):
        with pytest.raises(ValueError):
            to_chinastock("100001")

    def test_non_digit_raises(self):
        with pytest.raises(ValueError):
            to_chinastock("A00001")

    def test_wrong_length_raises(self):
        with pytest.raises(ValueError):
            to_chinastock("60051")  # 5 位

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            to_chinastock("")


class TestToWestock:
    def test_uppercase_to_lowercase(self):
        assert to_westock("SH600519") == "sh600519"

    def test_no_prefix(self):
        assert to_westock("600519") == "sh600519"

    def test_sz(self):
        assert to_westock("SZ000001") == "sz000001"

    def test_bj(self):
        assert to_westock("BJ830799") == "bj830799"


class TestToAkshare:
    def test_strip_prefix(self):
        assert to_akshare("SH600519") == "600519"

    def test_lowercase_prefix(self):
        assert to_akshare("sh600519") == "600519"

    def test_no_prefix_passthrough(self):
        assert to_akshare("600519") == "600519"
