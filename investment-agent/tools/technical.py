"""テクニカル分析・シグナル生成ツール（Tool 2）"""
import logging
from datetime import datetime, timedelta

import pandas as pd
import requests

import config

logger = logging.getLogger(__name__)

# 75日移動平均の算出には最低75件超のデータが必要なため、
# 「過去60日分」の指示に対し、計算に必要な最低限の件数を確保できるよう取得日数を広げる
HISTORY_DAYS = 100
RSI_PERIOD = 14
MACD_FAST, MACD_SLOW, MACD_SIGNAL = 12, 26, 9
BB_PERIOD, BB_NUM_STD = 20, 2
MA_SHORT, MA_MID, MA_LONG = 5, 25, 75


def fetch_price_history(code, days=HISTORY_DAYS):
    """指定銘柄の直近約days営業日分の株価データを日付昇順で取得する"""
    url = f"{config.JQUANTS_BASE_URL}/equities/bars/daily"
    end = datetime.now() - timedelta(days=1)
    start = end - timedelta(days=int(days * 1.6) + 10)
    params = {"code": code, "from": start.strftime("%Y-%m-%d"), "to": end.strftime("%Y-%m-%d")}

    try:
        response = requests.get(url, headers=config.get_headers(), params=params)
        response.raise_for_status()
        data = response.json()
        bars = data.get("daily_bars", data.get("bars", [])) if isinstance(data, dict) else data
        df = pd.DataFrame(bars)
    except Exception as e:
        logger.warning("%sの株価データ取得に失敗しました：%s", code, e)
        return pd.DataFrame()

    if df.empty or "Date" not in df.columns or "Close" not in df.columns:
        return pd.DataFrame()

    return df.sort_values("Date").tail(days).reset_index(drop=True)


def calc_rsi(close, period=RSI_PERIOD):
    """終値の系列からRSIを計算する（Wilderの平滑化を使用）"""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def calc_macd(close, fast=MACD_FAST, slow=MACD_SLOW, signal=MACD_SIGNAL):
    """終値の系列からMACDライン・シグナルライン・ヒストグラムを計算する"""
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    return macd_line, signal_line, macd_line - signal_line


def calc_bollinger_bands(close, period=BB_PERIOD, num_std=BB_NUM_STD):
    """終値の系列からボリンジャーバンド（中央線・上限・下限）を計算する"""
    middle = close.rolling(window=period).mean()
    std = close.rolling(window=period).std()
    return middle, middle + num_std * std, middle - num_std * std


def calc_moving_averages(close):
    """終値の系列から短期・中期・長期の移動平均線を計算する"""
    return (
        close.rolling(window=MA_SHORT).mean(),
        close.rolling(window=MA_MID).mean(),
        close.rolling(window=MA_LONG).mean(),
    )


def _judge_signal(rsi, macd_line, signal_line, prev_macd_line, prev_signal_line, ma_short, ma_mid, ma_long):
    """各指標の最新値から3条件の判定結果とシグナルを返す

    条件：1) RSIが40〜60、2) MACDがゴールデンクロス、3) 移動平均が上向き（5日>25日>75日）
    🟢買い：3条件すべて該当 / 🟡様子見：2条件該当 / 🔴見送り：RSI70以上 または 1条件以下
    """
    rsi_ok = pd.notna(rsi) and 40 <= rsi <= 60
    golden_cross = (
        pd.notna(macd_line) and pd.notna(signal_line)
        and pd.notna(prev_macd_line) and pd.notna(prev_signal_line)
        and prev_macd_line <= prev_signal_line and macd_line > signal_line
    )
    ma_uptrend = (
        pd.notna(ma_short) and pd.notna(ma_mid) and pd.notna(ma_long)
        and ma_short > ma_mid > ma_long
    )

    score = sum([rsi_ok, golden_cross, ma_uptrend])

    if pd.notna(rsi) and rsi >= 70:
        signal = "🔴見送り"
    elif score == 3:
        signal = "🟢買い"
    elif score == 2:
        signal = "🟡様子見"
    else:
        signal = "🔴見送り"

    return signal, rsi_ok, golden_cross, ma_uptrend


def analyze_one(code):
    """1銘柄分の株価履歴からテクニカル指標とシグナルを計算して辞書で返す（データ不足時はNone）"""
    history = fetch_price_history(code)
    min_required = max(MA_LONG, MACD_SLOW + MACD_SIGNAL, BB_PERIOD, RSI_PERIOD) + 1
    if len(history) < min_required:
        logger.warning("%sは株価データが不足しているため分析をスキップします（%d件）", code, len(history))
        return None

    close = history["Close"]
    rsi = calc_rsi(close)
    macd_line, signal_line, _ = calc_macd(close)
    _, bb_upper, bb_lower = calc_bollinger_bands(close)
    ma_short, ma_mid, ma_long = calc_moving_averages(close)

    signal, rsi_ok, golden_cross, ma_uptrend = _judge_signal(
        rsi.iloc[-1], macd_line.iloc[-1], signal_line.iloc[-1],
        macd_line.iloc[-2], signal_line.iloc[-2],
        ma_short.iloc[-1], ma_mid.iloc[-1], ma_long.iloc[-1],
    )

    return {
        "RSI": round(rsi.iloc[-1], 2),
        "MACD": round(macd_line.iloc[-1], 2),
        "MACDシグナル": round(signal_line.iloc[-1], 2),
        "BB上限": round(bb_upper.iloc[-1], 2),
        "BB下限": round(bb_lower.iloc[-1], 2),
        "MA5": round(ma_short.iloc[-1], 2),
        "MA25": round(ma_mid.iloc[-1], 2),
        "MA75": round(ma_long.iloc[-1], 2),
        "RSI条件": rsi_ok,
        "ゴールデンクロス": golden_cross,
        "MA上向き": ma_uptrend,
        "シグナル": signal,
    }


def run_technical_analysis(df):
    """スクリーニング通過銘柄のDataFrameにテクニカル指標とシグナル列を追加して返す

    ta-libが利用できない環境のため、RSI・MACD・ボリンジャーバンド・移動平均はpandasで計算する。
    """
    if df.empty:
        logger.info("分析対象の銘柄がありません")
        return df

    results = []
    for _, row in df.iterrows():
        code = row["Code"]
        try:
            analysis = analyze_one(code)
        except Exception as e:
            logger.warning("%sのテクニカル分析に失敗しました：%s", code, e)
            analysis = None

        merged = row.to_dict()
        if analysis is not None:
            merged.update(analysis)
        else:
            merged["シグナル"] = "🔴見送り"
        results.append(merged)

    return pd.DataFrame(results)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    from tools.screener import run_screener

    screened = run_screener()
    print(run_technical_analysis(screened))
