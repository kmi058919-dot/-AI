"""J-Quants APIへの接続テスト"""
from datetime import datetime, timedelta

import requests

import config


def get_last_business_day():
    """直近の営業日（土日を除いた日付）をYYYY-MM-DD形式で返す"""
    day = datetime.now() - timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day.strftime("%Y-%m-%d")


def main():
    """J-Quants APIに日足データを取得するリクエストを送り、結果を表示する"""
    code = "86970"
    date = get_last_business_day()
    url = f"{config.JQUANTS_BASE_URL}/equities/bars/daily"
    params = {"code": code, "date": date}

    try:
        response = requests.get(url, headers=config.get_headers(), params=params)
        print(response.text)
        response.raise_for_status()
        print("✅ API接続成功")
    except Exception as e:
        print(f"❌ エラー：{e}")


if __name__ == "__main__":
    main()
