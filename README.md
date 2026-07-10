# 🤖 Xiaomi-MiMoAi-discord (Mimo Bot)

> ⚠️ **免責事項 (Disclaimer)**  
> 本プロジェクト「Xiaomi-MiMoAi-discord」は、**Xiaomi 社（小米科技）とは一切関係のない、第三者による非公式な開発プロジェクトです。**  
> 本BotはXiaomi社の公式サポートや保証を受けるものではなく、プロジェクト名およびAPIの利用は、それぞれの利用規約に従い自己責任で行ってください。

## 🌟 プロジェクト概要
「Mimo（ミモ）」は、Xiaomiの **MiMo API** を活用したフレンドリーでユーモアのあるDiscord AI Botです。  
単なる質問応答だけでなく、最新のウェブ検索や画像認識機能を備え、ユーザーとの楽しい会話や深い対話を実現します。

## ✨ 主な機能
- 🧠 **高度な対話とキャラクター性**: MiMo-v2.5モデルを採用。友達のようなフランクで楽しい会話スタイルを基本とします。
- 🔍 **自動ウェブ検索 (Tavily)**: 最新情報が必要な質問をAIが自動判定し、Tavily APIを使用してリアルタイムのウェブ検索結果をもとに回答します。
- 🖼️ **画像認識 (Vision)**: 画像を添付して質問可能。画像はBase64エンコードしてAPIに送信します。
- 🛡️ **プライバシーとセキュリティ重視**: 
  - 会話履歴は外部クラウドではなく、ローカルのSQLiteデータベースで安全に管理。
  - **画像データはDBに保存せず、メモリ内処理のみ**でプライバシーを保護。
  - 管理者向けに緊急停止（`/stopall`）機能を搭載。
- 🛠️ **サーバーごとのカスタマイズ**: AI専用チャンネルの設定や、サーバー固有の指示（ペルソナ変更など）に対応。

## 🛠️ 技術スタック
- **Python 3.10+**
- **discord.py**: Discord Botフレームワーク
- **OpenAI SDK**: MiMo APIとの通信（OpenAI互換エンドポイント）
- **Tavily Python SDK**: リアルタイムウェブ検索
- **SQLite3**: ローカルデータベース（履歴・設定管理）
- **aiohttp**: 非同期画像ダウンロード

---

## 🚀 セットアップガイド

### 1. リポジトリのクローン
```bash
git clone https://github.com/Hurisan0909/MiMoAi-Discord-Bot-Unofficial.git
cd Xiaomi-MiMoAi-discord
```

### 2. 仮想環境の作成と依存パッケージのインストール
```bash
# 仮想環境の作成 (推奨)
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# パッケージのインストール
pip install discord.py openai tavily-python aiohttp
```

### 3. 環境変数の設定
Pythonファイルを編集し、設定フィードにIDやAPIを設定して下さい。
> **⚠️ セキュリティ注意**: `Xiaomi-MiMo.py` ファイルは `.gitignore` に追加し、絶対にGitHubにプッシュしないでください。

### 4. Botの実行
```bash
python Xiaomi-MiMo.py
```
※ 特定のサーバーでのみスラッシュコマンドを即座に同期したい場合は、コード内の `TEST_GUILD_ID` にサーバーIDを設定してください。未設定の場合はグローバルコマンドとして全サーバーに同期されます。

---

## 📖 スラッシュコマンド一覧

### 👤 一般ユーザー向け
| コマンド | 説明 |
| :--- | :--- |
| `/help` | 🤖 Botの操作マニュアルを表示します。 |
| `/ping` | 🏓 Botの応答速度（WebSocket疎通速度）を確認します。 |
| `/clear` | 🧹 自分の会話履歴をリセットし、処理中の応答を中断します。 |
| `/stop` | 🛑 現在実行中のAI応答を中断します。 |
| `/privacy` | 🔒 プライバシーポリシーを表示します。 |

### 🛡️ 管理者向け
| コマンド | 説明 |
| :--- | :--- |
| `/setchannel` | 📡 現在のチャンネルを「AI専用チャンネル」に設定します。 |
| `/stopall` | 🚨 **【緊急停止】** 全サーバーの処理を即座に停止し、新規受付を15秒間一時停止します。 |

---

## 🛡️ プライバシーポリシー
本Botはユーザーのプライバシー保護に最大限配慮した設計を行っています。
外部サイト: https://furisan.org/privacy/discord-bot/mimo-privacy.html

---

## 📝 クレジット
- **Developer**: [@hurisan_2006](https://x.com/Furisan_org)
- **Powered by**: MiMo (Xiaomi)
- **Search Engine**: Tavily AI
