import discord
from discord.ext import commands
from openai import AsyncOpenAI
from tavily import TavilyClient
import sqlite3
import asyncio
import logging
import os
import base64
import aiohttp

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ================= 設定エリア =================
MIMO_API_KEY = os.getenv("MIMO_API_KEY", "")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")
DB_NAME = os.getenv("DB_NAME", os.path.join(BASE_DIR, "mimo_bot.db"))
TEST_GUILD_ID = 0

MIMO_MODEL = os.getenv("MIMO_MODEL", "mimo-v2.5")

#以下をTrueにすると検索するか、しないかの判断を表示するデバッグ機能です。
DEBUG_SHOW_SEARCH_DECISION = False
# =============================================

# ロギング設定
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

# ベースとなるアイデンティティ
BASE_IDENTITY = f"""
Please speak in Japanese unless otherwise instructed by the user.
Your name is "Mimo(ミモ)"
The model you are using is "{MIMO_MODEL}", and you are a humorous and friendly AI created by [ @hurisan_2006 ].
You are not just an AI that explains things; you are a conversational AI aimed at enjoying dialogue.
Connect with the user in a friendly way, and instead of just giving short answers, ask questions back and provide follow-ups to keep the conversation going.
Your tone should be friendly and polite, and you should mix in light small talk when necessary.
Powered by mimo (Xiaomi)

[Code of Conduct]
Interact with the user with the closeness of a "friend", and speak frankly, using little to no honorifics.
You enjoy conversations mixed with jokes and humor. If you can provide a funny response, do so actively.
In situations where an explanation is needed, avoid technical jargon and explain things in an easy-to-understand, broken-down way.
Beyond just "explaining", empathize with the user's emotions and enjoy small talk.
If the user speaks in a language other than Japanese, such as English or Chinese, respond in the same language they used to address you.
"""

# クライアント初期化
mimo_client = AsyncOpenAI(api_key=MIMO_API_KEY, base_url="https://api.xiaomimimo.com/v1")
tavily = TavilyClient(api_key=TAVILY_API_KEY)

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# キャッシュ & 実行管理
server_settings_cache = {}
history_cache = {}
running_tasks = {}
_emergency_stop = False

# ================= ユーティリティ機能 =================
async def download_and_encode_image(url):
    """Discordの画像URLからBase64エンコードされた文字列を取得する"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    img_data = await resp.read()
                    return base64.b64encode(img_data).decode('utf-8')
    except Exception as e:
        logger.error(f"画像ダウンロードエラー: {e}")
    return None

def search_with_tavily(query):
    try:
        response = tavily.search(query=query, search_depth="basic", max_results=3)
        results = [f"出典: [{r['url']}]({r['url']})\n{r['content']}" for r in response.get('results', [])]
        return "\n\n".join(results) if results else ""
    except Exception as e:
        logger.error(f"Tavily検索エラー: {e}")
        return ""

# ================= データベース機能 =================
def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("""
        CREATE TABLE IF NOT EXISTS server_settings (
            guild_id TEXT PRIMARY KEY,
            channel_id TEXT,
            instruction TEXT
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conv_key TEXT,
            role TEXT,
            content TEXT
        )
        """)
        conn.commit()
        logger.info("データベース初期化完了")

def update_setting(guild_id, channel_id=None, instruction=None):
    gid = str(guild_id)
    curr_channel, curr_instr = get_server_settings(guild_id)
    curr_channel = channel_id or curr_channel
    curr_instr = instruction or curr_instr
    with get_db() as conn:
        conn.execute("INSERT OR REPLACE INTO server_settings VALUES (?, ?, ?)", 
                     (gid, str(curr_channel), curr_instr))
        conn.commit()
    server_settings_cache[gid] = (str(curr_channel), curr_instr)
    logger.info(f"サーバー設定更新: guild={gid}")

def get_server_settings(guild_id):
    gid = str(guild_id)
    if gid in server_settings_cache:
        return server_settings_cache[gid]
    with get_db() as conn:
        row = conn.execute("SELECT channel_id, instruction FROM server_settings WHERE guild_id = ?", (gid,)).fetchone()
        result = (row[0], row[1]) if row else (None, "フレンドリーで楽しい会話を心がけてください。")
        server_settings_cache[gid] = result
        return result

def add_history(conv_key, role, content):
    with get_db() as conn:
        conn.execute("INSERT INTO history (conv_key, role, content) VALUES (?, ?, ?)", (conv_key, role, content))
        conn.execute("""
        DELETE FROM history WHERE id IN (
            SELECT id FROM history WHERE conv_key = ? ORDER BY id DESC LIMIT -1 OFFSET 10
        )
        """, (conv_key,))
        conn.commit()
    if conv_key not in history_cache:
        history_cache[conv_key] = []
    history_cache[conv_key].append({"role": role, "content": content})
    if len(history_cache[conv_key]) > 10:
        history_cache[conv_key].pop(0)

def get_history(conv_key):
    if conv_key in history_cache:
        return history_cache[conv_key]
    with get_db() as conn:
        rows = conn.execute("SELECT role, content FROM history WHERE conv_key = ? ORDER BY id ASC", (conv_key,)).fetchall()
        history = [{"role": r[0], "content": r[1]} for r in rows]
        history_cache[conv_key] = history
        return history

def clear_history(conv_key):
    with get_db() as conn:
        conn.execute("DELETE FROM history WHERE conv_key = ?", (conv_key,))
        conn.commit()
    history_cache.pop(conv_key, None)

# ================= スラッシュコマンド =================
@bot.tree.command(name="help", description="🤖 Botの操作マニュアルを表示します")
async def help_cmd(interaction: discord.Interaction):
    embed = discord.Embed(title="🤖 Mimo Bot 操作マニュアル", color=0x3498db)
    embed.add_field(name="✨ 基本機能", value="設定チャンネルでMiMoAiがあなたの質問・会話にお答えします。\n**画像の送信にも対応しました！**", inline=False)
    embed.add_field(name="📡 一般ユーザー向け", value="`/reset` — 会話履歴リセット\n`/stop` — 応答中断\n`/privacy` — プライバシーポリシー表示", inline=False)
    embed.add_field(name="🛠️ 管理者向け", value="`/setchannel` — AI専用チャンネル設定\n`/stopall` — 全応答強制停止", inline=False)
    embed.set_footer(text="Developer: @hurisan_2006")
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="ping", description="🏓 Botの応答速度を確認します")
async def ping_cmd(interaction: discord.Interaction):
    await interaction.response.send_message(f"🏓 ぽんっ！ 生きてるよ！\nWebSocket疎通速度: `{bot.latency * 1000:.0f}ms`", ephemeral=True)

@bot.tree.command(name="setchannel", description="📡 このチャンネルをAI専用チャンネルに設定します（管理者のみ）")
@discord.app_commands.checks.has_permissions(administrator=True)
async def setchannel_cmd(interaction: discord.Interaction):
    update_setting(interaction.guild.id, channel_id=interaction.channel.id)
    await interaction.response.send_message("✅ AI専用チャンネルをここに設定しました！", ephemeral=True)

@bot.tree.command(name="clear", description="🧹 自分の会話履歴をリセットします")
async def reset_cmd(interaction: discord.Interaction):
    conv_key = f"{interaction.channel.id}:{interaction.user.id}"
    task = running_tasks.get(conv_key)
    if task and not task.done():
        task.cancel()
        await asyncio.sleep(0.05)
    clear_history(conv_key)
    await interaction.response.send_message("🧹 あなたの履歴をクリアし、処理中の応答を中断しました。", ephemeral=True)

@bot.tree.command(name="stop", description="🛑 現在のAI応答を中断します")
async def stop_cmd(interaction: discord.Interaction):
    key = f"{interaction.channel.id}:{interaction.user.id}"
    task = running_tasks.get(key)
    if task and not task.done():
        task.cancel()
        await interaction.response.send_message("🛑 応答の中断を要求しました。", ephemeral=True)
    else:
        await interaction.response.send_message("⛔ 現在実行中の応答はありません。", ephemeral=True)

@bot.tree.command(name="stopall", description="🛑 緊急停止：全処理を即座に停止（管理者のみ）")
@discord.app_commands.checks.has_permissions(administrator=True)
async def stopall_cmd(interaction: discord.Interaction):
    global _emergency_stop
    _emergency_stop = True
    canceled = 0
    for k, t in list(running_tasks.items()):
        if t and not t.done():
            t.cancel()
            canceled += 1
    running_tasks.clear()
    await interaction.response.send_message(f"🚨 緊急停止を発動しました。`{canceled}`件の処理を中断し、新規受付を一時停止しました。")
    asyncio.create_task(_reset_emergency_stop())

async def _reset_emergency_stop():
    global _emergency_stop
    await asyncio.sleep(15)
    _emergency_stop = False
    logger.info("緊急停止フラグを自動解除しました。新規受付を再開します。")

# ================= メイン処理 =================
async def handle_user_message(message, conv_key, custom_instruction):
    try:
        async with message.channel.typing():
            # 🖼️ 画像添付のチェック
            image_attachments = [att for att in message.attachments if att.content_type and att.content_type.startswith('image/')]
            
            # ユーザーメッセージの構築（テキストのみ or テキスト+画像）
            user_content = message.content
            if image_attachments:
                att = image_attachments[0]  # 複数画像が来てもまずは1枚目だけ処理
                b64_image = await download_and_encode_image(att.url)
                if b64_image:
                    user_content = [
                        {"type": "text", "text": message.content or "この画像について教えてください。"},
                        {"type": "image_url", "image_url": {"url": f"data:{att.content_type};base64,{b64_image}"}}
                    ]

            # 🔍 検索判定（画像がある場合はスキップしてAPIの負荷と混乱を防ぐ）
            search_data = ""
            if not image_attachments and message.content:
                check_prompt = (
                    "この質問に答えるために、最新のウェブ検索結果は必要ですか？\n"
                    "必要なら 'YES'、不要なら 'NO' とだけ答えてください。他の文字は一切出力しないでください。\n"
                    f"質問: {message.content}"
                )
                check_res = await mimo_client.chat.completions.create(
                    model=MIMO_MODEL,
                    messages=[{"role": "user", "content": check_prompt}],
                    temperature=0.0
                )
                decision = check_res.choices[0].message.content.strip()
                
                if DEBUG_SHOW_SEARCH_DECISION:
                    if "YES" in decision:
                        await message.channel.send(f"🔍 **[テスト] 検索判定**: `YES` (Tavilyで最新情報を取得します...)")
                    else:
                        await message.channel.send(f"🔍 **[テスト] 検索判定**: `NO` (検索は不要です)")
                
                if "YES" in decision:
                    search_data = await asyncio.to_thread(search_with_tavily, message.content)

            full_system_prompt = f"{BASE_IDENTITY}\n\n[サーバー固有設定]:\n{custom_instruction}"
            
            if search_data:
                full_system_prompt += f"""
【絶対厳守】
あなたは上記の[ウェブ検索結果]({search_data})に記述されている情報のみを根拠として回答してください。
あなたの内部知識や、学習済みの古いデータベースの情報は一切使用してはいけません。
もし検索結果に回答に必要な情報がない場合は、「申し訳ありませんが、検索結果に必要な情報が見つかりませんでした」と正直に答えてください。
"""

            chat_history = get_history(conv_key)
            messages = [{"role": "system", "content": full_system_prompt}]
            messages.extend(chat_history)
            messages.append({"role": "user", "content": user_content})

            response = await mimo_client.chat.completions.create(
                model=MIMO_MODEL, 
                messages=messages,
                temperature=0.9
            )
            ans_text = response.choices[0].message.content

            if len(ans_text) >= 5000:
                await message.channel.send("🚨 **【緊急停止】** AIの回答が5000文字を超えたため、送信を中止しました。")
                return

            # 💾 履歴の保存（Base64は保存せず、テキストのみを保存してDBとプライバシーを保護）
            history_text = message.content
            if image_attachments:
                history_text += "\n[画像が添付されました]"
                
            add_history(conv_key, "user", history_text)
            add_history(conv_key, "assistant", ans_text)

            limit = 1900
            for i in range(0, len(ans_text), limit):
                await message.channel.send(ans_text[i:i+limit])

    except asyncio.CancelledError:
        try:
            await message.channel.send("🛑 応答を中断しました。")
        except Exception:
            pass
        raise
    except Exception as e:
        logger.error(f"メッセージ処理エラー: {e}")
        await message.channel.send(f"⚠️ エラーが発生しました: `{e}`")
    finally:
        running_tasks.pop(conv_key, None)

@bot.event
async def on_ready():
    init_db()
    logger.info(f"✅ Logged in as {bot.user}")
    logger.info(f"📦 使用モデル: {MIMO_MODEL}")
    
    try:
        if TEST_GUILD_ID:
            # 🎯 指定されたサーバーにのみ即座同期（ギルドコマンド）
            guild = discord.Object(id=TEST_GUILD_ID)
            bot.tree.copy_global_to(guild=guild)
            synced = await bot.tree.sync(guild=guild)
            logger.info(f"🔄 [{guild.id}] サーバーに {len(synced)}個のコマンドを即座同期しました")
        else:
            # 🌍 全サーバーに同期（グローバルコマンド）
            synced = await bot.tree.sync()
            logger.info(f"🔄 {len(synced)}個のグローバルコマンドを同期しました")
    except Exception as e:
        logger.error(f"❌ コマンド同期エラー: {e}")

@bot.event
async def on_message(message):
    global _emergency_stop
    if message.author == bot.user or message.guild is None:
        return
    if message.author.bot:
        return
    if _emergency_stop:
        return

    conv_key = f"{message.channel.id}:{message.author.id}"
    target_channel_id, custom_instruction = get_server_settings(message.guild.id)

    if target_channel_id and str(message.channel.id) != target_channel_id:
        if bot.user not in message.mentions:
            return

    task = asyncio.create_task(handle_user_message(message, conv_key, custom_instruction))
    running_tasks[conv_key] = task
    try:
        await task
    except asyncio.CancelledError:
        pass

if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)