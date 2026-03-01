import discord
from openai import AsyncOpenAI
from tavily import TavilyClient
import sqlite3
import asyncio
import time
import csv
import unicodedata

# ================= 設定エリア =================
MIMO_API_KEY = "Your-toke"
TAVILY_API_KEY = "Your-toke"
DISCORD_TOKEN = "Your-token"
DB_NAME = "bot_memory.db"

# 指定する指示
BASE_IDENTITY = """
---text----
"""
# =============================================

mimo_client = AsyncOpenAI(api_key=MIMO_API_KEY, base_url="https://api.xiaomimimo.com/v1")
tavily = TavilyClient(api_key=TAVILY_API_KEY)

intents = discord.Intents.default()
intents.message_content = True
bot = discord.Client(intents=intents)

# --- キャッシュ機能 ---
server_settings_cache = {}
history_cache = {}
# 実行中の処理を保持してキャンセルできるようにする
running_tasks = {}

# --- データベース機能 ---

def init_db():
    conn = sqlite3.connect(DB_NAME)
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
            channel_id TEXT,
            role TEXT,
            content TEXT
        )
    """)
    conn.commit()
    conn.close()


def get_display_width(text: str) -> int:
    """テキストの表示幅を計算（日本語対応）
    ASCII文字は1幅、全角文字は2幅として計算
    """
    width = 0
    for char in str(text):
        # East Asian Width が 'F' (Fullwidth) または 'W' (Wide) なら2幅
        if unicodedata.east_asian_width(char) in ('F', 'W'):
            width += 2
        else:
            width += 1
    return width


def pad_to_display_width(text: str, target_width: int) -> str:
    """テキストを指定の表示幅にパディング（日本語対応）"""
    text = str(text)
    current_width = get_display_width(text)
    if current_width >= target_width:
        return text
    # 不足分を空白で埋める
    spaces_needed = target_width - current_width
    return text + ' ' * spaces_needed


def generate_ascii_table(text: str) -> str:
    """簡易的にCSVまたはパイプ区切りからASCII表を作る。
    各列の幅は最も長いセルに合わせて正確に計算する（日本語対応）。
    形式例:
    ヘッダ1,ヘッダ2\n値1,値2\n値3,値4
    または
    col1|col2\nval1|val2\nval3|val4
    """
    lines = [l for l in text.splitlines() if l.strip()]
    if not lines:
        return "(表の入力が空です)"

    # 区切り文字判定
    delim = ","
    if any("|" in l for l in lines):
        delim = "|"

    rows = []
    for ln in lines:
        # CSV 風にパース（簡易）
        parts = [c.strip() for c in ln.split(delim)]
        rows.append(parts)

    # 列数を揃える
    max_cols = max(len(r) for r in rows) if rows else 0
    if max_cols == 0:
        return "(有効な行がありません)"
    
    for r in rows:
        if len(r) < max_cols:
            r.extend([""] * (max_cols - len(r)))

    # 各列の最大表示幅を計算（全行と全列を走査）
    col_widths = [0] * max_cols
    for r in rows:
        for i, c in enumerate(r):
            cell_width = get_display_width(str(c))
            col_widths[i] = max(col_widths[i], cell_width)

    # 最小幅を設定（見栄え向上）
    col_widths = [max(w, 1) for w in col_widths]

    def sep_line():
        return "+" + "+".join(["-" * (w + 2) for w in col_widths]) + "+"

    def format_row(r):
        cells = []
        for i in range(max_cols):
            cell_text = str(r[i]) if i < len(r) else ""
            # 列幅に合わせてパディング（表示幅ベース）
            padded = pad_to_display_width(cell_text, col_widths[i])
            cells.append(" " + padded + " ")
        return "|" + "|".join(cells) + "|"

    out = []
    out.append(sep_line())
    for row_idx, r in enumerate(rows):
        out.append(format_row(r))
        # ヘッダ行の後にセパレータを追加
        if row_idx == 0:
            out.append(sep_line())
    out.append(sep_line())

    return "\n".join(out)


def convert_ai_tables(text: str) -> str:
    """回答の中からテーブルらしきブロックを検出し、ASCII表に変換する。
    複数ブロックがあれば順に変換する。コードブロック内は変換しない。
    """
    lines = text.splitlines()
    out_lines = []
    i = 0
    in_code_block = False
    while i < len(lines):
        line = lines[i]
        # コードブロック判定 (```)
        if line.strip().startswith('```'):
            in_code_block = not in_code_block
            out_lines.append(line)
            i += 1
            continue

        if in_code_block:
            out_lines.append(line)
            i += 1
            continue

        # テーブル候補判定: 区切りが '|' または ',' を含む行を起点に連続する行を収集
        if ('|' in line and line.count('|') >= 2) or (',' in line and line.count(',') >= 1):
            # collect block
            j = i
            block = []
            while j < len(lines) and (('|' in lines[j] and lines[j].count('|') >= 2) or (',' in lines[j] and lines[j].count(',') >= 1)):
                block.append(lines[j])
                j += 1

            # 最低2行以上のブロックなら変換を試みる
            if len(block) >= 2:
                # try to normalize delimiters: prefer '|' if present otherwise comma
                delim = '|' if any('|' in b for b in block) else ','
                # build payload without surrounding pipes
                payload_lines = []
                for b in block:
                    if delim == '|':
                        parts = [p.strip() for p in b.split('|') if p.strip() != '']
                    else:
                        parts = [p.strip() for p in b.split(',')]
                    payload_lines.append(','.join(parts))

                ascii_table = generate_ascii_table('\n'.join(payload_lines))
                out_lines.append('```')
                out_lines.extend(ascii_table.splitlines())
                out_lines.append('```')
                i = j
                continue

        out_lines.append(line)
        i += 1

    return '\n'.join(out_lines)

def update_setting(guild_id, channel_id=None, instruction=None):
    gid = str(guild_id)
    # キャッシュまたはDBから現在の設定を取得
    if gid in server_settings_cache:
        row = server_settings_cache[gid]
    else:
        conn = sqlite3.connect(DB_NAME)
        cur = conn.cursor()
        cur.execute("SELECT channel_id, instruction FROM server_settings WHERE guild_id = ?", (gid,))
        row = cur.fetchone()
        conn.close()

    curr_channel = channel_id if channel_id else (row[0] if row else None)
    curr_instr = instruction if instruction else (row[1] if row else "親切なアシスタントとして振る舞ってください。")
    curr_instr = instruction if instruction else (row[1] if row else "フレンドリーで楽しい会話を心がけてください。")

    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("INSERT OR REPLACE INTO server_settings (guild_id, channel_id, instruction) VALUES (?, ?, ?)", 
                (gid, str(curr_channel), curr_instr))
    conn.commit()
    conn.close()
    
    # キャッシュ更新
    server_settings_cache[gid] = (str(curr_channel), curr_instr)

def get_server_settings(guild_id):
    gid = str(guild_id)
    if gid in server_settings_cache:
        return server_settings_cache[gid]

    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT channel_id, instruction FROM server_settings WHERE guild_id = ?", (gid,))
    row = cur.fetchone()
    conn.close()
    
    result = row if row else (None, "親切なアシスタントとして振る舞ってください。")
    result = row if row else (None, "フレンドリーで楽しい会話を心がけてください。")
    server_settings_cache[gid] = result
    return result

def add_history(channel_id, role, content):
    cid = str(channel_id)
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("INSERT INTO history (channel_id, role, content) VALUES (?, ?, ?)", (cid, role, content))
    cur.execute("DELETE FROM history WHERE id IN (SELECT id FROM history WHERE channel_id = ? ORDER BY id DESC LIMIT -1 OFFSET 10)", (cid,))
    conn.commit()
    conn.close()
    
    # キャッシュ更新
    if cid in history_cache:
        history_cache[cid].append({"role": role, "content": content})
        if len(history_cache[cid]) > 10:
            history_cache[cid].pop(0)

def get_history(channel_id):
    cid = str(channel_id)
    if cid in history_cache:
        return history_cache[cid]

    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT role, content FROM history WHERE channel_id = ? ORDER BY id ASC", (cid,))
    rows = cur.fetchall()
    conn.close()
    
    history = [{"role": r[0], "content": r[1]} for r in rows]
    history_cache[cid] = history
    return history

def clear_history(channel_id):
    cid = str(channel_id)
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("DELETE FROM history WHERE channel_id = ?", (cid,))
    conn.commit()
    conn.close()
    
    if cid in history_cache:
        del history_cache[cid]

def search_with_tavily(query):
    try:
        response = tavily.search(query=query, search_depth="basic", max_results=3)
        results = [f"【出典: {r['url']}】\n{r['content']}" for r in response.get('results', [])]
        return "\n\n".join(results) if results else ""
    except:
        return ""

# --- メインイベント ---

@bot.event
async def on_ready():
    init_db()
    print(f'Logged in as {bot.user}')


async def handle_user_message(message, conv_key, custom_instruction):
    try:
        async with message.channel.typing():
            # 1. 検索判定
            check_res = await mimo_client.chat.completions.create(
                model="mimo-v2-flash",
                messages=[{"role": "user", "content": f"最新情報が必要？(SEARCH_NEEDED/SEARCH_NOT_NEEDED): {message.content}"}],
                temperature=0
            )
            
            search_data = ""
            if "SEARCH_NEEDED" in check_res.choices[0].message.content:
                search_data = await asyncio.to_thread(search_with_tavily, message.content)

            # 2. プロンプト組み立て
            full_system_prompt = f"{BASE_IDENTITY}\n\n[サーバー固有設定]:\n{custom_instruction}"
            if search_data:
                full_system_prompt += f"\n\n[ウェブ検索結果]:\n{search_data}"

            # 3. 履歴読み込み
            chat_history = get_history(conv_key)
            messages = [{"role": "system", "content": full_system_prompt}]
            messages.extend(chat_history)
            messages.append({"role": "user", "content": message.content})

            # 4. 回答生成
            response = await mimo_client.chat.completions.create(model="mimo-v2-flash", messages=messages)
            ans_text = response.choices[0].message.content

            # AIが表を生成しようとした場合はASCII表に変換する
            try:
                ans_text = convert_ai_tables(ans_text)
            except Exception:
                pass

            # 5. 5000文字以上の緊急停止
            if len(ans_text) >= 5000:
                await message.channel.send(f"🚨 **【緊急停止】** AIの回答が5000文字を超えたため、送信を中止しました。（文字数: {len(ans_text)}）")
                return

            # 6. 履歴保存
            add_history(conv_key, "user", message.content)
            add_history(conv_key, "assistant", ans_text)

            # 7. 分割送信
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
        await message.channel.send(f"⚠️ エラーが発生しました: {e}")
    finally:
        # 終了したら running_tasks から削除
        try:
            if conv_key in running_tasks:
                del running_tasks[conv_key]
        except Exception:
            pass

@bot.event
async def on_message(message):
    # 自分のメッセージは無視
    if message.author == bot.user:
        return
    
    # DM（サーバー外のメッセージ）は無視
    if message.guild is None:
        return

    # 会話キー (チャンネル別ユーザー単位の会話を保持)
    conv_key = f"{message.channel.id}:{message.author.id}"

    # --- ヘルプコマンド ---
    if message.content == "mimo!help":
        embed = discord.Embed(title="🤖 Mimo Bot 操作マニュアル", color=0x3498db)
        embed.add_field(name="✨ 基本機能", value="設定されたチャンネルでMiMoAiがあなたの質問・会話にお答えします。", inline=False)
        embed.add_field(name="📡 一般ユーザー向けコマンド", value=(
            "`mimo!ping` — Botが生きているか確認します。\n"
            "`mimo!reset` — 自分の会話履歴をリセットします。\n"
            "`mimo!stop` — 自分の現在の応答を中断します（チャンネル内で動作）。\n"
        ), inline=False)
        embed.add_field(name="🛠️ 管理者向けコマンド", value=(
            "`mimo!setchannel` — このチャンネルをAI専用チャンネルに設定します（管理者のみ）。\n"
            "`mimo!stop all` — すべての進行中の応答を強制停止します（管理者のみ）。"
        ), inline=False)
        embed.set_footer(text="Developer: @hurisan_2006")
        await message.channel.send(embed=embed)
        return

    # --- Pingコマンド ---
    if message.content == "mimo!ping":
        raw_ping = bot.latency * 1000
        await message.channel.send(f"🏓 ぽんっ！ 生きてるよ！\nWebSocket疎通速度: {raw_ping:.0f}ms")
        return

    # チャンネル設定
    if message.content == "mimo!setchannel":
        if message.author.guild_permissions.administrator:
            update_setting(message.guild.id, channel_id=message.channel.id)
            await message.channel.send(f"✅ AI専用チャンネルをここに設定したよ！")
        return

    # `mimo!instruction` コマンドは廃止されました

    # 履歴リセット
    if message.content == "mimo!reset":
        clear_history(conv_key)
        await message.channel.send("🧹 履歴をクリアしたよ。")
        return

    # 緊急停止コマンド（自分の会話を止める / 管理者は全停止可能）
    if message.content.startswith("mimo!stop"):
        cmd = message.content.strip()
        # 自分の会話を停止
        if cmd == "mimo!stop":
            t = running_tasks.get(conv_key)
            if t and not t.done():
                t.cancel()
                await message.channel.send("🛑 応答の中断を要求しました。")
            else:
                await message.channel.send("⛔ 現在実行中の応答はありません。")
            return

        # 管理者のみ: 全停止
        if cmd == "mimo!stop all":
            if message.author.guild_permissions.administrator:
                canceled = 0
                for k, t in list(running_tasks.items()):
                    if t and not t.done():
                        t.cancel()
                        canceled += 1
                await message.channel.send(f"🛑 全ての応答を中断しました（{canceled}件）。")
            else:
                await message.channel.send("🔒 このコマンドを実行するには管理者権限が必要です。")
            return

    # 動作対象チャンネルかチェック（設定チャンネルまたはメンションで会話可）
    target_channel_id, custom_instruction = get_server_settings(message.guild.id)
    # チャンネル指定があり、かつ現在のチャンネルが指定と異なる場合は、ボットへのメンションでのみ応答
    if target_channel_id is not None and str(message.channel.id) != target_channel_id:
        if bot.user not in message.mentions:
            return

    # 実際の処理は別タスクにして、緊急停止できるようにする
    task = asyncio.create_task(handle_user_message(message, conv_key, custom_instruction))
    running_tasks[conv_key] = task
    try:
        await task
    except asyncio.CancelledError:
        # 停止は handle_user_message 内で通知するためここでは無視
        pass

bot.run(DISCORD_TOKEN)
