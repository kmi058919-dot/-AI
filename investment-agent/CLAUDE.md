# 投資AIエージェント｜指示書

## プロジェクト概要
日本株の短期（スイング）トレード支援エージェント。
毎朝7:30に自動実行し、デイリーレポートを生成する。

## 技術スタック
- Python 3.11
- J-Quants API V2（認証：.envのJQUANTS_API_KEY）
- pandas（データ処理）
- ta-lib（テクニカル指標計算）
- SQLite（ポートフォリオ管理）
- schedule（自動実行）

## ファイルの役割
- main.py：全ツールを順番に実行してレポートを生成
- config.py：APIキー読み込みと共通設定
- tools/screener.py：銘柄スクリーニング（Tool 1）
- tools/technical.py：テクニカル分析・シグナル生成（Tool 2）
- tools/news.py：決算・ニュース分析（Tool 3）
- tools/portfolio.py：ポートフォリオ管理（Tool 4）
- reports/：日次レポートの保存先

## コーディングルール
- APIキーは必ず.envから読む。コードへの直書き禁止
- エラーが出てもスキップしてログに記録し、処理を止めない
- すべての関数にdocstringを書く（日本語でOK）
- コメントは日本語でOK

## レポートのルール
- reports/YYYY-MM-DD.md に保存する
- 必ず含める項目：上位5銘柄・保有状況・リスク要因・今週の決算予定
- 損切りライン到達銘柄は🔴で強調する
- シグナル強度は🟢買い / 🟡様子見 / 🔴見送り で表現

## 実行方法
- 手動実行：python main.py
- 自動実行：cronで毎朝7:30に設定（Week4で対応）
