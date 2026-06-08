"""共通設定：APIキーの読み込みとリクエストヘッダーの生成"""
import os

from dotenv import load_dotenv

load_dotenv()

JQUANTS_API_KEY = os.getenv("JQUANTS_API_KEY")
JQUANTS_BASE_URL = "https://api.jquants.com/v2"

# 四本値・出来高の実APIレスポンスでの列名は短縮表記の場合があるため、
# 候補名から内部標準名（Close/Volume）へ正規化する（MktNm/CoNameと同様の命名傾向を考慮した候補）
PRICE_COLUMN_CANDIDATES = {
    "Close": ["Close", "ClosePrice", "Cl", "CloseVal", "C", "close"],
    "Volume": ["Volume", "TradingVolume", "Vol", "TrdVol", "V", "volume"],
}


def get_headers():
    """J-Quants APIへのリクエストに使う共通ヘッダーを返す"""
    return {"x-api-key": JQUANTS_API_KEY}


def normalize_price_columns(df):
    """四本値・出来高DataFrameの列名を内部標準名（Close/Volume）に正規化して返す

    実レスポンスの列名が候補のいずれにも一致しない場合は変更せずそのまま返す
    （呼び出し側でログ出力し、実際の列名から正しい名前を特定できるようにする）。
    """
    if df.empty:
        return df

    rename_map = {}
    for standard, candidates in PRICE_COLUMN_CANDIDATES.items():
        if standard in df.columns:
            continue
        for candidate in candidates:
            if candidate in df.columns:
                rename_map[candidate] = standard
                break

    return df.rename(columns=rename_map) if rename_map else df
