"""测试 src.data_sources.neodata_source 的 token 管理与 HTTP 调用。"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.data_sources.neodata_source import (
    DEFAULT_ENDPOINT,
    TOKEN_FILE,
    TOKEN_TTL_SECONDS,
    NeodataSource,
    _read_token,
    has_valid_token,
    save_token,
)


@pytest.fixture
def tmp_token_file(tmp_path, monkeypatch):
    """重定向 TOKEN_FILE 到临时目录。"""
    fake = tmp_path / ".workbuddy" / ".neodata_token"
    monkeypatch.setattr("src.data_sources.neodata_source.TOKEN_FILE", fake)
    return fake


class TestTokenManagement:
    def test_read_token_missing(self, tmp_token_file):
        assert _read_token() is None

    def test_read_token_valid(self, tmp_token_file):
        import time

        data = {"token": "abc123", "saved_at": int(time.time())}
        tmp_token_file.parent.mkdir(parents=True, exist_ok=True)
        tmp_token_file.write_text(json.dumps(data))
        assert _read_token() == "abc123"

    def test_read_token_expired(self, tmp_token_file):
        import time

        data = {"token": "abc123", "saved_at": int(time.time()) - TOKEN_TTL_SECONDS - 1}
        tmp_token_file.parent.mkdir(parents=True, exist_ok=True)
        tmp_token_file.write_text(json.dumps(data))
        assert _read_token() is None

    def test_read_token_invalid_json(self, tmp_token_file):
        tmp_token_file.parent.mkdir(parents=True, exist_ok=True)
        tmp_token_file.write_text("not-json")
        assert _read_token() is None

    def test_save_then_read(self, tmp_token_file):
        save_token("test-token")
        assert tmp_token_file.exists()
        assert _read_token() == "test-token"
        # 文件权限 600（Windows 上可能不支持，但 Linux 上是）
        if hasattr(tmp_token_file.stat(), "st_mode"):
            mode = tmp_token_file.stat().st_mode & 0o777
            assert mode in (0o600, 0o666)  # Windows 常见是 666

    def test_has_valid_token(self, tmp_token_file):
        assert has_valid_token() is False
        save_token("valid-token")
        assert has_valid_token() is True


class TestNeodataSourceABC:
    def test_not_implemented_methods(self):
        src = NeodataSource(token="dummy")
        with pytest.raises(NotImplementedError):
            src.get_lhb(None, "2025-12-15")
        with pytest.raises(NotImplementedError):
            src.get_limit_up_pool("2025-12-15")
        with pytest.raises(NotImplementedError):
            src.get_sector_constituents("机器人")
        with pytest.raises(NotImplementedError):
            src.get_sector_perf("机器人", "2025-11-01", "2025-12-15")

    def test_role_and_name(self):
        assert NeodataSource.role.value == "primary"
        assert NeodataSource.name == "neodata"


class TestNaturalQuery:
    def test_post_called_with_correct_payload(self):
        src = NeodataSource(token="test-token")
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": "ok"}
        mock_resp.raise_for_status = MagicMock()
        with patch("src.data_sources.neodata_source.requests.post", return_value=mock_resp) as m:
            src.natural_query("贵州茅台 2025-12-15 收盘价")
            # 验证调用参数
            args, kwargs = m.call_args
            assert args[0] == DEFAULT_ENDPOINT
            assert kwargs["headers"]["Authorization"] == "Bearer test-token"
            assert kwargs["json"]["query"] == "贵州茅台 2025-12-15 收盘价"
            assert kwargs["json"]["channel"] == "neodata"
            assert kwargs["json"]["sub_channel"] == "workbuddy"

    def test_no_token_raises(self):
        src = NeodataSource()  # 无 token
        with patch("src.data_sources.neodata_source._read_token", return_value=None):
            with pytest.raises(RuntimeError, match="token 不可用"):
                src.natural_query("test")


class TestGetQuoteForValidation:
    def test_returns_dataframe_with_raw_response(self):
        src = NeodataSource(token="test-token")
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": {"close": 1500, "volume": 1000}}
        with patch("src.data_sources.neodata_source.requests.post", return_value=mock_resp):
            df = src.get_quote_for_validation("SH600519", "2025-12-15")
            assert len(df) == 1
            assert df["date"].iloc[0] == "2025-12-15"
            assert df["symbol"].iloc[0] == "SH600519"
            assert "raw_response" in df.columns
            assert "1500" in df["raw_response"].iloc[0]
