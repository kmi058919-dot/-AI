"""ポートフォリオ管理ツール（Tool 4）"""
import logging
import os
import sqlite3
from datetime import datetime, timedelta

import pandas as pd
import requests

import config

logger = logging.getLogger(__name__)

DB_PATH = os.path.join("data", "portfolio.db")
DEFAULT_STOP_LOSS_RATE = 0.07  # 損切りラインのデフォルト：購入価格の-7%


def _get_connection():
    """SQLiteデータベースへの接続を返す（holdingsテーブルが無ければ作成する）"""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS holdings (
            code TEXT NOT NULL,
            name TEXT,
            buy_price REAL,
            quantity INTEGER,
            buy_date TEXT,
            stop_loss REAL
        )
        """
    )
    return conn


def add_holding(code, name, buy_price, quantity, buy_date=None, stop_loss=None):
    """保有銘柄をholdingsテーブルに追加する

    損切りラインを指定しない場合は、購入価格の-7%（DEFAULT_STOP_LOSS_RATE）を自動設定する。
    """
    buy_date = buy_date or datetime.now().strftime("%Y-%m-%d")
    if stop_loss is None:
        stop_loss = round(buy_price * (1 - DEFAULT_STOP_LOSS_RATE), 2)

    conn = _get_connection()
    try:
        conn.execute(
            "INSERT INTO holdings (code, name, buy_price, quantity, buy_date, stop_loss) VALUES (?, ?, ?, ?, ?, ?)",
            (code, name, buy_price, quantity, buy_date, stop_loss),
        )
        conn.commit()
        logger.info(
            "保有銘柄を追加しました：%s（%s）買値%s円 x %s株　損切りライン%s円",
            code, name, buy_price, quantity, stop_loss,
        )
    except Exception as e:
        logger.error("保有銘柄の追加に失敗しました：%s", e)
    finally:
        conn.close()


def get_holdings():
    """保有銘柄一覧をDataFrameで返す"""
    conn = _get_connection()
    try:
        return pd.read_sql_query("SELECT * FROM holdings", conn)
    except Exception as e:
        logger.error("保有銘柄一覧の取得に失敗しました：%s", e)
        return pd.DataFrame()
    finally:
        conn.close()


def remove_holding(code):
    """指定した銘柄コードの保有銘柄を削除する"""
    conn = _get_connection()
    try:
        cursor = conn.execute("DELETE FROM holdings WHERE code = ?", (code,))
        conn.commit()
        logger.info("保有銘柄を削除しました：%s（%d件）", code, cursor.rowcount)
    except Exception as e:
        logger.error("保有銘柄の削除に失敗しました：%s", e)
    finally:
        conn.close()


def _latest_business_day():
    """直近の営業日（土日を除く）をYYYY-MM-DD形式で返す"""
    day = datetime.now() - timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day.strftime("%Y-%m-%d")


def fetch_current_prices(codes):
    """指定した銘柄コードのリストについて、直近営業日の終値（現在値）を取得する"""
    url = f"{config.JQUANTS_BASE_URL}/equities/bars/daily"
    date = _latest_business_day()

    records = []
    for code in codes:
        try:
            response = requests.get(url, headers=config.get_headers(), params={"code": code, "date": date})
            response.raise_for_status()
            data = response.json()
            bars = data.get("daily_bars", data.get("bars", [])) if isinstance(data, dict) else data
            if bars:
                records.append({"Code": code, "Close": bars[-1].get("Close")})
        except Exception as e:
            logger.warning("%sの現在値取得に失敗しました：%s", code, e)
            continue

    return pd.DataFrame(records)


def _merge_with_current_prices(current_prices_df):
    """保有銘柄一覧と現在値をCodeで突き合わせ、現在値が取得できた銘柄のみのDataFrameを返す"""
    holdings = get_holdings()
    if holdings.empty or current_prices_df.empty or "Code" not in current_prices_df.columns:
        return pd.DataFrame()

    merged = holdings.merge(
        current_prices_df[["Code", "Close"]], left_on="code", right_on="Code", how="left"
    )
    return merged.dropna(subset=["Close"])


def check_stop_loss(current_prices_df):
    """現在値が損切りライン（stop_loss）以下まで下落した保有銘柄を抽出して返す"""
    merged = _merge_with_current_prices(current_prices_df)
    if merged.empty:
        return pd.DataFrame()

    triggered = merged[merged["Close"] <= merged["stop_loss"]].copy()
    if triggered.empty:
        return pd.DataFrame()

    for _, row in triggered.iterrows():
        logger.warning(
            "🔴損切りライン到達：%s（%s）現在値%s円 ≦ 損切りライン%s円",
            row["code"], row["name"], row["Close"], row["stop_loss"],
        )

    triggered["損切りフラグ"] = "🔴損切りライン到達"
    return (
        triggered[["code", "name", "buy_price", "quantity", "stop_loss", "Close", "損切りフラグ"]]
        .rename(columns={"Close": "現在値"})
        .reset_index(drop=True)
    )


def calc_pnl(current_prices_df):
    """保有銘柄の含み損益（金額・率）を計算したDataFrameを返す"""
    merged = _merge_with_current_prices(current_prices_df)
    if merged.empty:
        return pd.DataFrame()

    merged = merged.copy()
    merged["含み損益額"] = ((merged["Close"] - merged["buy_price"]) * merged["quantity"]).round(2)
    merged["含み損益率"] = ((merged["Close"] - merged["buy_price"]) / merged["buy_price"] * 100).round(2)

    return (
        merged[["code", "name", "buy_price", "quantity", "Close", "含み損益額", "含み損益率"]]
        .rename(columns={"Close": "現在値"})
        .reset_index(drop=True)
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    add_holding("7203", "トヨタ自動車", 2800, 1)

    holdings = get_holdings()
    print("=== 保有銘柄一覧 ===")
    print(holdings)

    prices = fetch_current_prices(holdings["code"].tolist())
    print("=== 現在値 ===")
    print(prices)

    print("=== 含み損益 ===")
    print(calc_pnl(prices))

    print("=== 損切りラインチェック ===")
    print(check_stop_loss(prices))
