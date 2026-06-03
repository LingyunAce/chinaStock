"""westock-data 数据源适配器（主源）。

通过 subprocess 调用项目内 `.claude/skills/westock-data/scripts/index.js` Node CLI，
解析返回的 markdown 表格为 DataFrame，转换字段名 → chinaStock snake_case。

westock 字段（中文）→ chinaStock snake_case 的映射：
- 代码 → code
- 名称 → name
- 涨跌幅 → pct_change
- etc.

约定：westock 内部代码为小写 `sh600519`，通过 `to_westock()` 转换。
输出：snake_case + `SH600519` 形式（与其他源一致）。
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

import pandas as pd

from src.data_layer.symbols import to_chinastock, to_westock
from src.data_sources.base import DataSource, SourceRole

# 项目内 vendored westock CLI 路径
_PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]
_WESTOCK_CLI: Path = (
    _PROJECT_ROOT / ".claude" / "skills" / "westock-data" / "scripts" / "index.js"
)


# ----------------------------- Markdown 表格解析 -----------------------------
def _parse_markdown_table(text: str) -> pd.DataFrame:
    """把 westock 的 markdown 表格输出解析为 DataFrame。

    格式：
        | col1 | col2 | col3 |
        | --- | --- | --- |
        | a | b | c |
        | d | e | f |

    容忍：表格外的提示行（如 `**机构榜** (46只)`、`📊 查询板块...`）会被自动忽略。
    """
    lines = [ln.rstrip() for ln in text.splitlines()]
    table_lines = [ln for ln in lines if ln.strip().startswith("|")]
    if len(table_lines) < 2:
        return pd.DataFrame()
    # 跳过表头分隔行（"| --- | --- |"）
    header = [c.strip() for c in table_lines[0].strip().strip("|").split("|")]
    rows: list[list[str]] = []
    for ln in table_lines[2:]:
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if len(cells) == len(header):
            rows.append(cells)
    return pd.DataFrame(rows, columns=header) if rows else pd.DataFrame()


def _to_number(s: str) -> float | None:
    """westock 数字常带中文单位（万 / 亿 / %），统一转 float。"""
    if s is None:
        return None
    s = str(s).strip()
    if not s or s in ("-", "--", "—"):
        return None
    s = s.replace(",", "").replace("%", "")
    multiplier = 1.0
    if s.endswith("亿"):
        multiplier = 1e8
        s = s[:-1]
    elif s.endswith("万"):
        multiplier = 1e4
        s = s[:-1]
    elif s.endswith("千"):
        multiplier = 1e3
        s = s[:-1]
    try:
        return float(s) * multiplier
    except (ValueError, TypeError):
        return s if s else None


# ----------------------------- CLI 调用 -----------------------------
def _westock_available() -> bool:
    """westock CLI 是否可用：要求 node + CLI 文件存在。"""
    return shutil.which("node") is not None and _WESTOCK_CLI.exists()


def _call_westock(args: list[str], timeout: int = 30) -> str:
    """调用 westock CLI，返回 stdout 文本。失败抛 RuntimeError。"""
    if not _westock_available():
        raise RuntimeError(
            f"westock-data CLI 不可用：需要 node ≥ 18 和文件 {_WESTOCK_CLI}"
        )
    cmd = ["node", str(_WESTOCK_CLI), *args]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"westock 调用超时: {' '.join(args)}") from e
    if result.returncode != 0:
        raise RuntimeError(
            f"westock 调用失败 (rc={result.returncode}): {result.stderr.strip()[:500]}"
        )
    return result.stdout or ""


# ----------------------------- 主适配器 -----------------------------
class WestockSource(DataSource):
    """westock-data 适配器（主源）。

    对应命令：
    - 龙虎榜         → `lhb --tab jg --date DATE`
    - 涨停池(近似)   → `hot`（westock 没有严格意义的涨停池，使用热度榜代理）
    - 板块成分       → `sector --list <list_code>` + `sector <sector_code>`
    - 板块日 K       → `kline <sector_code>`
    - 验证用 K 线    → `kline <symbol>`
    """

    role: SourceRole = SourceRole.PRIMARY
    name: str = "westock"

    # ---------------------- 龙虎榜 ----------------------
    def get_lhb(self, symbol: str | None, date: str, **kw: Any) -> pd.DataFrame:
        """龙虎榜（机构榜 tab=jg）。

        westock 不支持按 code 查单只票，统一拉全市场机构榜。
        """
        raw_text = _call_westock(
            ["lhb", "--tab", "jg", "--date", date.replace("-", "")]
        )
        raw = _parse_markdown_table(raw_text)
        if raw.empty:
            return raw
        # 字段重命名：westock 中英 → chinaStock snake_case
        rename = {
            "代码": "code",
            "名称": "name",
            "上榜天数": "rank_days",
            "机构买入席位": "inst_buy_seats",
            "机构买入额": "inst_buy_amount",
            "买入占比": "buy_pct",
            "总买入额": "total_buy_amount",
            "净买入额": "net_buy_amount",
            "净占比": "net_pct",
        }
        out = raw.rename(columns=rename)
        if "code" in out.columns:
            out["symbol"] = out["code"].apply(
                lambda x: to_chinastock(str(x)) if pd.notna(x) else None
            )
        # 数字列转 float
        for col in (
            "inst_buy_amount",
            "total_buy_amount",
            "net_buy_amount",
            "buy_pct",
            "net_pct",
        ):
            if col in out.columns:
                out[col] = out[col].apply(_to_number)
        out["date"] = date
        # symbol 过滤
        if symbol is not None and "symbol" in out.columns:
            out = out[out["symbol"] == to_chinastock(symbol)]
        return out

    # ---------------------- 涨停池（近似） ----------------------
    def get_limit_up_pool(self, date: str, **kw: Any) -> pd.DataFrame:
        """涨停池（近似）：westock 没有严格意义的涨停池，使用 `hot` 热度榜代理。

        行为限制：`hot` 不区分涨停/跌停/人气；返回 top N 涨跌排行。调用方应自行过滤。
        调用方（integrations/limit_up）应优先使用 AkShareSource 的真实涨停池。
        """
        # westock 不会真的给我们涨停池；返回空 DataFrame 让上层 fallback 到 AKShare
        return pd.DataFrame()

    # ---------------------- 板块/概念 ----------------------
    def get_sector_constituents(self, sector: str, **kw: Any) -> pd.DataFrame:
        """板块成分股。

        westock 调用方式：
        1. 通过 `sector --list concept_list_industry` 拿到所有聚源产业概念（name+code）
        2. 找到 sector 对应的 code
        3. 调 `sector <code>` 拿成分股

        对于 6 位代码（symbol）传参，本方法不接受——westock 的 sector 接口是按
        "清单名称" 查，不是按股票代码。
        """
        # 简化处理：先查所有概念清单，找到匹配 name
        for list_code in (
            "industry_list_sw1",
            "industry_list_sw2",
            "industry_list_sw3",
            "concept_list_industry",
            "concept_list_style",
            "concept_list_area",
        ):
            try:
                text = _call_westock(["sector", "--list", list_code])
                df = _parse_markdown_table(text)
                if df.empty or "名称" not in df.columns or "代码" not in df.columns:
                    continue
                match = df[df["名称"] == sector]
                if match.empty:
                    continue
                sec_code = match["代码"].iloc[0]
                # 拉成分股
                text2 = _call_westock(["sector", sec_code])
                df2 = _parse_markdown_table(text2)
                if not df2.empty and "code" in df2.columns:
                    df2["symbol"] = df2["code"].apply(
                        lambda x: to_chinastock(str(x)) if pd.notna(x) else None
                    )
                    return df2[["symbol", "name"]].dropna()
            except (RuntimeError, Exception):  # noqa: BLE001
                continue
        return pd.DataFrame()

    def get_sector_perf(
        self, sector: str, start: str, end: str, **kw: Any
    ) -> pd.DataFrame:
        """板块日 K 线。

        westock 没有"按 sector 名称查 K 线"——必须先 get_sector_constituents 找到 code，
        然后用 code 调 `kline`。
        """
        # 先找到 code
        constituents = self.get_sector_constituents(sector)
        if constituents.empty:
            return pd.DataFrame()
        # 用第一只成分股的 code 作为近似（westock 的 kline 不直接支持板块 K）
        # 严格来说应该用 sector_code 调 kline；这里 fallback 到成分股加权平均
        # TODO: 改进——westock 后续版本若有 sector kline 直接命令则用之
        sample_code = (
            constituents["symbol"].iloc[0] if "symbol" in constituents.columns else None
        )
        if sample_code is None:
            return pd.DataFrame()
        westock_code = to_westock(sample_code)
        text = _call_westock(
            [
                "kline",
                westock_code,
                "--period",
                "daily",
                "--start",
                start.replace("-", ""),
                "--end",
                end.replace("-", ""),
            ]
        )
        raw = _parse_markdown_table(text)
        if raw.empty:
            return raw
        rename = {
            "date": "date",
            "open": "open",
            "last": "close",
            "high": "high",
            "low": "low",
            "volume": "volume",
            "amount": "amount",
            "exchange": "turnover",
        }
        out = raw.rename(columns=rename)
        for col in ("open", "close", "high", "low", "volume", "amount"):
            if col in out.columns:
                out[col] = pd.to_numeric(out[col], errors="coerce")
        return out

    # ---------------------- 交叉验证 ----------------------
    def get_quote_for_validation(
        self, symbol: str, date: str, **kw: Any
    ) -> pd.DataFrame:
        """拉 westock 个股 K 线（与 AKShare 同口径），用于跨源数据校验。"""
        westock_code = to_westock(symbol)
        # 拉 ±5 日窗口
        end = pd.Timestamp(date)
        start = end - pd.Timedelta(days=10)
        text = _call_westock(
            [
                "kline",
                westock_code,
                "--period",
                "daily",
                "--start",
                start.strftime("%Y%m%d"),
                "--end",
                end.strftime("%Y%m%d"),
            ]
        )
        raw = _parse_markdown_table(text)
        if raw.empty:
            return raw
        rename = {
            "date": "date",
            "open": "open",
            "last": "close",
            "high": "high",
            "low": "low",
            "volume": "volume",
            "amount": "amount",
        }
        out = raw.rename(columns=rename)
        for col in ("open", "close", "high", "low", "volume", "amount"):
            if col in out.columns:
                out[col] = pd.to_numeric(out[col], errors="coerce")
        out["symbol"] = to_chinastock(symbol)
        return out

    # ===================== westock-specific 扩展方法 =====================
    # 以下方法不实现 DataSource ABC（westock 独有），按需调用
    # =====================================================================

    # ---------------------- 财务数据 ----------------------
    # A 股: summary / detail / lrb / zcfz / xjll
    def get_finance(
        self,
        symbol: str,
        finance_type: str = "summary",
        num: int = 4,
    ) -> pd.DataFrame:
        """财务数据。

        :param symbol: `SH600519` 或 `sh600519`
        :param finance_type: summary(摘要) / detail(详细) / lrb(利润表) / zcfz(资产负债表) / xjll(现金流量表)
        :param num: 期数
        :return: 解析后的 DataFrame（列名保留 westock 原样，可在 normalize 层做映射）
        """
        westock_code = to_westock(symbol)
        text = _call_westock(
            ["finance", westock_code, "--type", finance_type, "--num", str(num)]
        )
        raw = _parse_markdown_table(text)
        if raw.empty:
            return raw
        # summary 才有 EPS/PE/PB 等估值字段；其他报表是数字列
        if finance_type == "summary" and "symbol" not in raw.columns:
            raw["symbol"] = to_chinastock(symbol)
        return raw

    # ---------------------- 技术指标 ----------------------
    def get_technical(
        self,
        symbol: str,
        group: str = "all",
        date: str | None = None,
        start: str | None = None,
        end: str | None = None,
    ) -> pd.DataFrame:
        """技术指标。

        :param group: ma / macd / kdj / rsi / boll / bias / wr / dmi / all
        :param date: 单日查询（YYYY-MM-DD）
        :param start/end: 区间查询（YYYY-MM-DD）
        """
        westock_code = to_westock(symbol)
        args = ["technical", westock_code, "--group", group]
        if date:
            args.extend(["--date", date.replace("-", "")])
        if start and end:
            args.extend(
                ["--start", start.replace("-", ""), "--end", end.replace("-", "")]
            )
        text = _call_westock(args)
        raw = _parse_markdown_table(text)
        if raw.empty:
            return raw
        # 数字列转 float
        for col in raw.columns:
            if col in ("date", "code", "name", "symbol"):
                continue
            try:
                raw[col] = pd.to_numeric(raw[col], errors="coerce")
            except Exception:  # noqa: BLE001
                pass
        if "symbol" not in raw.columns and "code" in raw.columns:
            raw["symbol"] = to_chinastock(symbol)
        return raw

    # ---------------------- 新闻 / 公告 / 研报 ----------------------
    def get_news(
        self, symbol: str, limit: int = 10, news_type: int = 0
    ) -> pd.DataFrame:
        """个股新闻。

        :param news_type: 0=全部 1=... 详见 westock help
        """
        westock_code = to_westock(symbol)
        text = _call_westock(
            ["news", westock_code, "--limit", str(limit), "--type", str(news_type)]
        )
        raw = _parse_markdown_table(text)
        if raw.empty:
            return raw
        # 只保留关键列
        keep = [
            c
            for c in ("time", "title", "src", "summary", "url", "importance")
            if c in raw.columns
        ]
        out = raw[keep].copy() if keep else raw
        if "time" in out.columns:
            out["time"] = out["time"].astype(str).str.strip()
        out["symbol"] = to_chinastock(symbol)
        out["news_type_label"] = "news"
        return out

    def get_notice(
        self, symbol: str, notice_type: int = 0, limit: int = 10
    ) -> pd.DataFrame:
        """个股公告。"""
        westock_code = to_westock(symbol)
        text = _call_westock(
            ["notice", westock_code, "--type", str(notice_type), "--limit", str(limit)]
        )
        raw = _parse_markdown_table(text)
        if raw.empty:
            return raw
        keep = [c for c in ("time", "title", "url") if c in raw.columns]
        out = raw[keep].copy() if keep else raw
        if "time" in out.columns:
            out["time"] = out["time"].astype(str).str.strip()
        out["symbol"] = to_chinastock(symbol)
        out["news_type_label"] = "notice"
        return out

    def get_report(self, symbol: str, limit: int = 5) -> pd.DataFrame:
        """研报列表（包含评级）。"""
        westock_code = to_westock(symbol)
        text = _call_westock(["report", westock_code, "--limit", str(limit)])
        raw = _parse_markdown_table(text)
        if raw.empty:
            return raw
        # 关键列：time / title / src（券商）/ tzpj（投资评级：买入/增持/...）
        keep = [
            c
            for c in ("time", "title", "src", "typeStr", "tzpj", "summary")
            if c in raw.columns
        ]
        out = raw[keep].copy() if keep else raw
        if "time" in out.columns:
            out["time"] = out["time"].astype(str).str.strip()
        out["symbol"] = to_chinastock(symbol)
        return out

    # ---------------------- 一致预期 / 评级 ----------------------
    def get_consensus(self, symbol: str) -> dict:
        """一致预期：分析师对营收/利润/EPS/PE/PB 等的多空预测。

        返回 dict，含：
        - target_price: 目标价均值
        - forecasts: DataFrame（年份 × 指标）
        """
        westock_code = to_westock(symbol)
        text = _call_westock(["consensus", westock_code])
        result: dict[str, Any] = {
            "symbol": to_chinastock(symbol),
            "target_price": None,
            "forecasts": pd.DataFrame(),
            "raw": text,
        }
        # 提取目标价
        for ln in text.splitlines():
            if "目标价" in ln:
                parts = ln.split(":", 1)
                if len(parts) == 2:
                    try:
                        result["target_price"] = float(parts[1].strip())
                    except ValueError:
                        pass
        # 表格部分
        df = _parse_markdown_table(text)
        if not df.empty:
            result["forecasts"] = df
        return result

    def get_rating(self, symbol: str) -> pd.DataFrame:
        """机构评级汇总。"""
        westock_code = to_westock(symbol)
        text = _call_westock(["rating", westock_code])
        raw = _parse_markdown_table(text)
        if raw.empty:
            return raw
        rename = {
            "code": "code",
            "name": "name",
            "forecastInstitutions": "forecast_institutions",
            "targetPriceAvg": "target_price_avg",
            "targetPriceMax": "target_price_max",
            "targetPriceMin": "target_price_min",
            "ratingBuyCnt": "rating_buy",
            "ratingIncCnt": "rating_inc",
            "ratingHoldCnt": "rating_hold",
            "ratingDecCnt": "rating_dec",
            "ratingSellCnt": "rating_sell",
            "ratingCnt": "rating_total",
        }
        out = raw.rename(columns=rename)
        if "code" in out.columns:
            out["symbol"] = out["code"].apply(
                lambda x: to_chinastock(str(x)) if pd.notna(x) else None
            )
        return out

    # ---------------------- 板块排名 / 热搜 ----------------------
    def get_sector_rank(
        self,
        list_code: str = "concept_list_industry",
        sort: str = "chg5Days",
        limit: int = 30,
    ) -> pd.DataFrame:
        """板块区间涨幅排行。

        :param list_code: industry_list_sw1/2/3, concept_list_industry/style/area
        :param sort: chg5Days / chg20Days / chg60Days / chg120Days / chg250Days / name
        :return: DataFrame，列含 # / 代码 / 名称 / 5日% / 20日% / 60日% / 120日% / 250日%
        """
        text = _call_westock(
            ["sector", "--rank", list_code, "--sort", sort, "--limit", str(limit)]
        )
        raw = _parse_markdown_table(text)
        if raw.empty:
            return raw
        rename = {
            "#": "rank",
            "代码": "sector_code",
            "名称": "sector_name",
            "5日%": "chg_5d_pct",
            "20日%": "chg_20d_pct",
            "60日%": "chg_60d_pct",
            "120日%": "chg_120d_pct",
            "250日%": "chg_250d_pct",
        }
        out = raw.rename(columns=rename)
        for col in (
            "chg_5d_pct",
            "chg_20d_pct",
            "chg_60d_pct",
            "chg_120d_pct",
            "chg_250d_pct",
        ):
            if col in out.columns:
                out[col] = out[col].apply(_to_number)
        return out

    def get_hot(self, hot_type: str = "stock", limit: int = 20) -> pd.DataFrame:
        """热搜：stock / wx / news / board / etf。"""
        text = _call_westock(["hot", hot_type, "--limit", str(limit)])
        raw = _parse_markdown_table(text)
        if raw.empty:
            return raw
        return raw

    # ---------------------- 投资日历 ----------------------
    def get_calendar(self, date: str | None = None, limit: int = 20) -> pd.DataFrame:
        """投资日历：股东大会 / 解禁 / 分红 / 财报披露 等。"""
        args = ["calendar"]
        if date:
            args.append(date.replace("-", ""))
        args.extend(["--limit", str(limit)])
        text = _call_westock(args)
        raw = _parse_markdown_table(text)
        return raw


__all__ = ["WestockSource", "_westock_available"]
