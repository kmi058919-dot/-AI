"""銘柄スクリーニングツール（Tool 1）"""
import logging
from datetime import datetime, timedelta

import pandas as pd
import requests

import config

logger = logging.getLogger(__name__)

TARGET_MARKETS = ["プライム", "スタンダード"]
VOLUME_RATIO_THRESHOLD = 1.5
MIN_PRICE = 500
MA_WINDOW = 5


def _recent_business_days(n):
    """直近n営業日分の日付（YYYY-MM-DD、古い順）のリストを返す"""
    days = []
    day = datetime.now() - timedelta(days=1)
    while len(days) < n:
        if day.weekday() < 5:
            days.append(day.strftime("%Y-%m-%d"))
        day -= timedelta(days=1)
    return list(reversed(days))


def fetch_listed_companies():
    """上場銘柄一覧を取得し、東証プライム・スタンダード市場の銘柄に絞って返す"""
    url = f"{config.JQUANTS_BASE_URL}/equities/master"
    try:
        response = requests.get(url, headers=config.get_headers())
        response.raise_for_status()
        data = response.json()
        df = pd.DataFrame(data.get("data", data.get("equities", data)) if isinstance(data, dict) else data)
    except Exception as e:
        logger.error("銘柄一覧の取得に失敗しました：%s", e)
        return pd.DataFrame()

    if "MarketCodeName" not in df.columns:
        logger.error("MarketCodeName列が見つかりませんでした：%s", list(df.columns))
        return pd.DataFrame()

    return df[df["MarketCodeName"].isin(TARGET_MARKETS)].reset_index(drop=True)


def fetch_daily_bars(date):
    """指定日の全銘柄の四本値・出来高を取得する"""
    url = f"{config.JQUANTS_BASE_URL}/equities/bars/daily"
    try:
        response = requests.get(url, headers=config.get_headers(), params={"date": date})
        response.raise_for_status()
        data = response.json()
        bars = data.get("data", data.get("daily_bars", data.get("bars", []))) if isinstance(data, dict) else data
        return pd.DataFrame(bars)
    except Exception as e:
        logger.warning("%sの株価データ取得に失敗しました：%s", date, e)
        return pd.DataFrame()


def _passes_screening(history):
    """1銘柄分の時系列データ（日付昇順）がスクリーニング条件を満たすか判定する

    条件：出来高が前日比150%以上、株価500円以上、終値が5日移動平均より上
    """
    if len(history) < MA_WINDOW + 1:
        return False

    latest = history.iloc[-1]
    previous = history.iloc[-2]
    ma5 = history["Close"].iloc[-(MA_WINDOW + 1):-1].mean()

    volume_ok = previous["Volume"] > 0 and latest["Volume"] / previous["Volume"] >= VOLUME_RATIO_THRESHOLD
    price_ok = latest["Close"] >= MIN_PRICE
    ma_ok = latest["Close"] > ma5

    return volume_ok and price_ok and ma_ok


def run_screener():
    """銘柄スクリーニングを実行し、条件を満たした銘柄のDataFrameを返す（結果はCSVにも保存する）"""
    companies = fetch_listed_companies()
    if companies.empty:
        logger.error("対象銘柄が取得できなかったため、スクリーニングを中止します")
        return pd.DataFrame()

    target_codes = set(companies["Code"])

    bars_by_date = []
    for date in _recent_business_days(MA_WINDOW + 1):
        bars = fetch_daily_bars(date)
        if not bars.empty:
            bars_by_date.append(bars)

    if not bars_by_date:
        logger.error("株価データが取得できなかったため、スクリーニングを中止します")
        return pd.DataFrame()

    all_bars = pd.concat(bars_by_date, ignore_index=True)
    all_bars = all_bars[all_bars["Code"].isin(target_codes)]
    all_bars = all_bars.sort_values(["Code", "Date"]).reset_index(drop=True)

    passed = []
    for code, history in all_bars.groupby("Code"):
        try:
            if _passes_screening(history):
                latest = history.iloc[-1]
                company = companies.loc[companies["Code"] == code].iloc[0]
                passed.append({
                    "Code": code,
                    "CompanyName": company.get("CompanyName"),
                    "MarketCodeName": company.get("MarketCodeName"),
                    "Date": latest["Date"],
                    "Close": latest["Close"],
                    "Volume": latest["Volume"],
                })
        except Exception as e:
            logger.warning("%sのスクリーニング判定に失敗しました：%s", code, e)
            continue

    result = pd.DataFrame(passed)

    today = datetime.now().strftime("%Y-%m-%d")
    output_path = f"data/screened_{today}.csv"
    result.to_csv(output_path, index=False, encoding="utf-8-sig")
    logger.info("スクリーニング結果を%sに保存しました（%d件）", output_path, len(result))

    return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    print(run_screener())
