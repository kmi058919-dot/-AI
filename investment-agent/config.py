"""共通設定：APIキーの読み込みとリクエストヘッダーの生成"""
import os

from dotenv import load_dotenv

load_dotenv()

JQUANTS_API_KEY = os.getenv("JQUANTS_API_KEY")
JQUANTS_BASE_URL = "https://api.jquants.com/v2"


def get_headers():
    """J-Quants APIへのリクエストに使う共通ヘッダーを返す"""
    return {"x-api-key": JQUANTS_API_KEY}
