"""日本株デイリーレポート生成（メイン処理）"""
import argparse
import logging
import os
import time
from datetime import datetime

import pandas as pd
import requests
import schedule

import config
from tools.news import run_news_analysis
from tools.portfolio import calc_pnl, check_stop_loss, fetch_current_prices, get_holdings
from tools.screener import run_screener
from tools.technical import run_technical_analysis

logger = logging.getLogger(__name__)

SIGNAL_RANK = {"🟢買い": 0, "🟡様子見": 1, "🔴見送り": 2}
REQUIRED_ANALYSIS_COLUMNS = {
    "CompanyName": "-",
    "RSI": pd.NA,
    "シグナル": "🔴見送り",
    "決算リスク": pd.NA,
    "決算発表日": pd.NA,
}

RUN_TIME = "07:30"
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday"]

# J-Quants取引カレンダーAPIのHolidayDivision値（V1の仕様に準拠：1=営業日、2=半日立会、3=非営業日でも取引あり）
TRADING_DAY_DIVISIONS = {"1", "2", "3"}


def _format_currency(value):
    """金額を「1,234円」の形式の文字列に変換する（欠損値は「-」）"""
    if pd.isna(value):
        return "-"
    return f"{value:,.0f}円"


def _build_top5_table(analyzed):
    """シグナル強度順（🟢→🟡→🔴、同強度はRSI昇順）に並べた注目銘柄TOP5のMarkdownテーブルを生成する"""
    if analyzed.empty:
        return "（本日はスクリーニング通過銘柄がありませんでした）"

    ranked = analyzed.copy()
    for column, default in REQUIRED_ANALYSIS_COLUMNS.items():
        if column not in ranked.columns:
            ranked[column] = default

    ranked["_signal_rank"] = ranked["シグナル"].map(SIGNAL_RANK).fillna(99)
    ranked = ranked.sort_values(["_signal_rank", "RSI"], na_position="last").head(5)

    lines = [
        "| 銘柄コード | 銘柄名 | シグナル | RSI | 決算リスク |",
        "|-----------|-------|---------|-----|----------|",
    ]
    for _, row in ranked.iterrows():
        rsi_text = "-" if pd.isna(row["RSI"]) else f"{row['RSI']:.0f}"
        risk_text = row["決算リスク"] if pd.notna(row["決算リスク"]) else "なし"
        lines.append(
            f"| {row['Code']} | {row['CompanyName']} | {row['シグナル']} | {rsi_text} | {risk_text} |"
        )
    return "\n".join(lines)


def _build_holdings_table(holdings, holdings_pnl):
    """保有ポジションのMarkdownテーブルを生成する

    現在値が取得できた銘柄はholdings_pnlの内容を、取得できなかった銘柄は
    取得値・損切りラインのみを「-（現在値取得失敗）」として表示する。
    """
    if holdings.empty:
        return "（保有銘柄はありません）"

    lines = [
        "| 銘柄 | 取得値 | 現在値 | 損益 | 損切りライン |",
        "|-----|-------|-------|-----|------------|",
    ]

    priced_codes = set(holdings_pnl["code"]) if not holdings_pnl.empty else set()

    for _, row in holdings.iterrows():
        if row["code"] in priced_codes:
            pnl_row = holdings_pnl.loc[holdings_pnl["code"] == row["code"]].iloc[0]
            pnl_text = f"{pnl_row['含み損益額']:+,.0f}円（{pnl_row['含み損益率']:+.2f}%）"
            current_price_text = _format_currency(pnl_row["現在値"])
        else:
            pnl_text = "-（現在値取得失敗）"
            current_price_text = "-"

        lines.append(
            f"| {row['code']} {row['name']} | {_format_currency(row['buy_price'])} "
            f"| {current_price_text} | {pnl_text} | {_format_currency(row['stop_loss'])} |"
        )
    return "\n".join(lines)


def _build_risk_section(stop_loss_hits, earnings_soon):
    """リスク要因セクション（損切りライン到達銘柄・今週の決算予定銘柄）の本文を生成する"""
    lines = []

    if stop_loss_hits.empty:
        lines.append("- 損切りライン到達銘柄：なし")
    else:
        for _, row in stop_loss_hits.iterrows():
            lines.append(
                f"- 🔴 {row['code']} {row['name']}：現在値{_format_currency(row['現在値'])} "
                f"が損切りライン{_format_currency(row['stop_loss'])}に到達"
            )

    if earnings_soon.empty:
        lines.append("- 今週の決算予定銘柄：なし")
    else:
        for _, row in earnings_soon.iterrows():
            lines.append(
                f"- {row['決算リスク']} {row['Code']} {row['CompanyName']}："
                f"{row['決算発表日']} に決算発表予定"
            )

    return "\n".join(lines)


def _build_earnings_section(earnings_soon):
    """今週の決算予定セクションの本文（Markdownテーブル）を生成する"""
    if earnings_soon.empty:
        return "今週中に決算発表を予定している注目銘柄はありません。"

    lines = [
        "| 銘柄コード | 銘柄名 | 決算発表日 | 状態 |",
        "|-----------|-------|-----------|------|",
    ]
    for _, row in earnings_soon.iterrows():
        lines.append(f"| {row['Code']} | {row['CompanyName']} | {row['決算発表日']} | {row['決算リスク']} |")
    return "\n".join(lines)


def generate_report(analyzed, holdings, holdings_pnl, stop_loss_hits, earnings_soon, screened_count):
    """各種分析結果から日次レポートのMarkdown文字列を組み立てる"""
    today = datetime.now().strftime("%Y-%m-%d")

    return f"""# 📊 日本株 デイリーレポート｜{today}

## 🔍 本日のスクリーニング結果
スクリーニング通過銘柄数：{screened_count}社

## 🏆 注目銘柄TOP5（シグナル強度順）
{_build_top5_table(analyzed)}

## 💼 保有ポジション
{_build_holdings_table(holdings, holdings_pnl)}

## ⚠️ リスク要因
{_build_risk_section(stop_loss_hits, earnings_soon)}

## 🗓️ 今週の決算予定
{_build_earnings_section(earnings_soon)}
"""


def main():
    """全ツールを順に実行し、デイリーレポートを生成してreports/に保存する"""
    logger.info("Tool 1: 銘柄スクリーニングを実行します")
    screened = run_screener()

    logger.info("Tool 2: テクニカル分析を実行します")
    analyzed = run_technical_analysis(screened)

    logger.info("Tool 3: 決算・ニュース分析を実行します")
    analyzed = run_news_analysis(analyzed)

    logger.info("Tool 4: 保有ポジションを取得します")
    holdings = get_holdings()
    if holdings.empty:
        holdings_pnl = pd.DataFrame()
        stop_loss_hits = pd.DataFrame()
    else:
        current_prices = fetch_current_prices(holdings["code"].tolist())
        holdings_pnl = calc_pnl(current_prices)
        stop_loss_hits = check_stop_loss(current_prices)

    if "決算リスク" in analyzed.columns:
        earnings_soon = analyzed[analyzed["決算リスク"].notna()].copy()
    else:
        earnings_soon = pd.DataFrame()

    report = generate_report(analyzed, holdings, holdings_pnl, stop_loss_hits, earnings_soon, len(screened))

    today = datetime.now().strftime("%Y-%m-%d")
    os.makedirs("reports", exist_ok=True)
    output_path = f"reports/{today}.md"
    with open(output_path, "w", encoding="utf-8-sig") as f:
        f.write(report)

    print(f"[完了] レポート生成完了：{output_path}")


def _setup_logging():
    """コンソールと logs/YYYY-MM-DD.log の両方にログを出力するよう設定する（日付が変わったら呼び直す）"""
    os.makedirs("logs", exist_ok=True)
    log_path = f"logs/{datetime.now().strftime('%Y-%m-%d')}.log"

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)

    formatter = logging.Formatter("%(asctime)s %(levelname)s: %(message)s")

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)


def is_trading_day(date_str=None):
    """指定日（省略時は今日）がJ-Quants取引カレンダー上の取引日かどうかを判定する

    APIから判定できない場合は、平日（月〜金）であれば取引日とみなすフォールバックを行う。
    """
    date_str = date_str or datetime.now().strftime("%Y-%m-%d")
    is_weekday = datetime.strptime(date_str, "%Y-%m-%d").weekday() < 5

    url = f"{config.JQUANTS_BASE_URL}/markets/trading-calendar"
    try:
        response = requests.get(url, headers=config.get_headers(), params={"date": date_str})
        response.raise_for_status()
        data = response.json()
        records = (
            data.get("data", data.get("trading_calendar", data.get("calendar", [])))
            if isinstance(data, dict) else data
        )
    except Exception as e:
        logger.warning("取引カレンダーの取得に失敗したため、平日判定で代用します：%s", e)
        return is_weekday

    for record in records:
        if record.get("Date") == date_str:
            return str(record.get("HolidayDivision", "")) in TRADING_DAY_DIVISIONS

    logger.warning("取引カレンダーに%sのレコードが無いため、平日判定で代用します", date_str)
    return is_weekday


def scheduled_job():
    """スケジュール実行用ジョブ：取引日（平日かつ祝日でない日）であればレポート生成を実行する"""
    _setup_logging()
    today_str = datetime.now().strftime("%Y-%m-%d")

    if datetime.now().weekday() >= 5:
        logger.info("本日（%s）は土日のため実行をスキップします", today_str)
        return

    if not is_trading_day(today_str):
        logger.info("本日（%s）は祝日等の休場日のため実行をスキップします", today_str)
        return

    logger.info("本日（%s）は取引日のため自動実行を開始します", today_str)
    main()


def _format_next_run(scheduled_time=RUN_TIME):
    """次回実行予定時刻を「HH:MM」形式の文字列で返す"""
    next_run = schedule.next_run()
    return next_run.strftime("%H:%M") if next_run else scheduled_time


def run_daemon():
    """平日7:30に自動実行するデーモンモードを起動する（バックグラウンド常駐）"""
    for weekday in WEEKDAYS:
        getattr(schedule.every(), weekday).at(RUN_TIME).do(scheduled_job)

    print(f"[起動] 投資エージェント起動 次の実行：{_format_next_run()}")
    logger.info("デーモンモードで起動しました（平日%s実行）。次回実行予定：%s", RUN_TIME, _format_next_run())

    while True:
        schedule.run_pending()
        time.sleep(30)


def parse_args():
    """コマンドライン引数を解析する（--daemonでバックグラウンド自動実行モード）"""
    parser = argparse.ArgumentParser(description="投資AIエージェント")
    parser.add_argument(
        "--daemon", action="store_true",
        help="バックグラウンド自動実行モード（平日7:30に自動実行、休場日は取引カレンダーで判定してスキップ）",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    _setup_logging()

    if args.daemon:
        run_daemon()
    else:
        logger.info("即時実行モードで起動しました")
        main()
