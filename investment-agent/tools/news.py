"""決算・ニュース分析ツール（Tool 3）"""
import logging
from datetime import datetime

import pandas as pd
import requests

import config

logger = logging.getLogger(__name__)

# 決算発表までの残り日数に応じたフラグ（当日に近いものから優先的に判定する）
FLAG_EARNINGS_TODAY = "🚨決算当日"
FLAG_EARNINGS_RISK = "⚠️決算リスク"
FLAG_EARNINGS_SOON = "📅決算近い"

# シグナルを1段階引き下げる対象とするフラグ（名称に「リスク」を含む差し迫った決算のみ）
DOWNGRADE_TRIGGER_FLAGS = {FLAG_EARNINGS_TODAY, FLAG_EARNINGS_RISK}

SIGNAL_DOWNGRADE = {
    "🟢買い": "🟡様子見",
    "🟡様子見": "🔴見送り",
    "🔴見送り": "🔴見送り",
}

CODE_COLUMN_CANDIDATES = ["Code", "code"]
DATE_COLUMN_CANDIDATES = ["AnnouncementDate", "EarningsDate", "Date", "date"]


def _find_column(df, candidates):
    """候補名のリストの中から実際に存在する列名を返す（無ければNone）"""
    for name in candidates:
        if name in df.columns:
            return name
    return None


def fetch_earnings_calendar():
    """決算発表予定日のカレンダーを取得する"""
    url = f"{config.JQUANTS_BASE_URL}/equities/earnings-calendar"
    try:
        response = requests.get(url, headers=config.get_headers())
        response.raise_for_status()
        data = response.json()
        records = (
            data.get("data", data.get("earnings_calendar", data.get("earnings", [])))
            if isinstance(data, dict) else data
        )
        return pd.DataFrame(records)
    except Exception as e:
        logger.error("決算発表予定の取得に失敗しました：%s", e)
        return pd.DataFrame()


def _days_until(date_str):
    """指定日付（YYYY-MM-DD）が今日から何日後かを返す（過去日や不正な日付はNone）"""
    try:
        target = datetime.strptime(str(date_str), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None

    delta = (target - datetime.now().date()).days
    return delta if delta >= 0 else None


def _earnings_flag(days_until):
    """決算発表までの残り日数からフラグを判定する（対象外ならNone）"""
    if days_until is None:
        return None
    if days_until == 0:
        return FLAG_EARNINGS_TODAY
    if days_until <= 3:
        return FLAG_EARNINGS_RISK
    if days_until <= 7:
        return FLAG_EARNINGS_SOON
    return None


def _next_earnings(calendar, code, code_col, date_col):
    """指定銘柄の直近（今日以降）の決算発表予定日と残り日数を返す（無ければ(None, None)）"""
    rows = calendar.loc[calendar[code_col] == code, date_col]

    upcoming = []
    for date_str in rows:
        days_until = _days_until(date_str)
        if days_until is not None:
            upcoming.append((days_until, str(date_str)))

    if not upcoming:
        return None, None

    upcoming.sort(key=lambda x: x[0])
    return upcoming[0]


def run_news_analysis(df):
    """決算発表予定を分析し、決算リスクフラグの付与とシグナル引き下げを行ったDataFrameを返す

    フラグ：決算発表まで3日以内→⚠️決算リスク／7日以内→📅決算近い／当日→🚨決算当日
    ⚠️決算リスクと🚨決算当日が立った銘柄はシグナルを1段階引き下げる（🟢買い→🟡様子見→🔴見送り）
    """
    if df.empty:
        logger.info("分析対象の銘柄がありません")
        return df

    calendar = fetch_earnings_calendar()
    code_col = _find_column(calendar, CODE_COLUMN_CANDIDATES)
    date_col = _find_column(calendar, DATE_COLUMN_CANDIDATES)

    result = df.copy()

    if calendar.empty or code_col is None or date_col is None:
        logger.warning("決算発表予定が取得できなかったため、決算リスク判定をスキップします")
        result["決算発表日"] = None
        result["決算リスク"] = None
        return result

    earnings_dates = []
    flags = []
    signals = []

    for _, row in result.iterrows():
        code = row["Code"]
        try:
            days_until, earnings_date = _next_earnings(calendar, code, code_col, date_col)
            flag = _earnings_flag(days_until)
        except Exception as e:
            logger.warning("%sの決算発表予定の判定に失敗しました：%s", code, e)
            earnings_date, flag = None, None

        earnings_dates.append(earnings_date)
        flags.append(flag)

        signal = row.get("シグナル")
        if flag in DOWNGRADE_TRIGGER_FLAGS and signal in SIGNAL_DOWNGRADE:
            signal = SIGNAL_DOWNGRADE[signal]
        signals.append(signal)

    result["決算発表日"] = earnings_dates
    result["決算リスク"] = flags
    result["シグナル"] = signals
    return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    from tools.screener import run_screener
    from tools.technical import run_technical_analysis

    screened = run_screener()
    analyzed = run_technical_analysis(screened)
    print(run_news_analysis(analyzed))
