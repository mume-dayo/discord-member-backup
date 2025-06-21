import discord
from discord.ext import commands
from discord import app_commands
from flask import Flask, request, redirect, session, url_for, render_template_string
import requests
import os
import threading
import asyncio
from urllib.parse import urlencode
import json
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
bot = commands.Bot(command_prefix='!', intents=intents)
app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'your-secret-key-here')
DISCORD_CLIENT_ID = os.environ.get('DISCORD_CLIENT_ID')
DISCORD_CLIENT_SECRET = os.environ.get('DISCORD_CLIENT_SECRET')
DISCORD_BOT_TOKEN = os.environ.get('DISCORD_BOT_TOKEN')
REDIRECT_URI = os.environ.get('REDIRECT_URI')
if not REDIRECT_URI:
    print("❌ REDIRECT_URI環境変数が設定されていません。")
    print("環境変数で以下を設定してください:")
    print("REDIRECT_URI=https://your-app-name.onrender.com/callback")
    exit(1)
authenticated_users = {}
DISCORD_API_BASE = 'https://discord.com/api'
DISCORD_OAUTH_URL = f'{DISCORD_API_BASE}/oauth2/authorize'
DISCORD_TOKEN_URL = f'{DISCORD_API_BASE}/oauth2/token'
DISCORD_USER_URL = f'{DISCORD_API_BASE}/users/@me'
DISCORD_GUILDS_URL = f'{DISCORD_API_BASE}/users/@me/guilds'
@app.route('/')
def index():
    return render_template_string('''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Discord OAuth Bot</title>
        <style>
            body { font-family: Arial, sans-serif; max-width: 600px; margin: 50px auto; padding: 20px; }
            .btn { background: #5865F2; color: white; padding: 12px 20px; text-decoration: none; border-radius: 5px; display: inline-block; margin: 10px 0; }
            .btn:hover { background: #4752C4; }
            .success { color: green; }
            .error { color: red; }
        </style>
    </head>
    <body>
        <h1>Discord OAuth Bot</h1>
        <p>このBotはDiscord OAuth認証を行い、認証したユーザーを指定されたサーバーに招待します。</p>

        {% if session.get('user') %}
            <div class="success">
                <h3>認証済み: {{ session['user']['username'] }}#{{ session['user']['discriminator'] }}</h3>
                <p>あなたは正常に認証されました！</p>
                <a href="/logout" class="btn">ログアウト</a>
            </div>
        {% else %}
            <a href="/auth" class="btn">Discordで認証</a>
        {% endif %}

        <h3>使用方法:</h3>
        <ol>
            <li>上記のボタンでDiscord認証を行う</li>
            <li>Botがいるサーバーで <code>/invite_user &lt;user_id&gt; &lt;target_server_id&gt;</code> コマンドを使用</li>
            <li>認証済みユーザーが指定されたサーバーに招待される</li>
        </ol>
    </body>
    </html>
    ''')
@app.route('/auth')
def auth():
    params = {
        'client_id': DISCORD_CLIENT_ID,
        'redirect_uri': REDIRECT_URI,
        'response_type': 'code',
        'scope': 'identify guilds guilds.join'
    }

    auth_url = f'{DISCORD_OAUTH_URL}?{urlencode(params)}'
    return redirect(auth_url)

@app.route('/callback')
def callback():
    code = request.args.get('code')

    if not code:
        return 'Authorization failed', 400
    token_data = {
        'client_id': DISCORD_CLIENT_ID,
        'client_secret': DISCORD_CLIENT_SECRET,
        'grant_type': 'authorization_code',
        'code': code,
        'redirect_uri': REDIRECT_URI
    }
    headers = {'Content-Type': 'application/x-www-form-urlencoded'}

    token_response = requests.post(DISCORD_TOKEN_URL, data=token_data, headers=headers)

    if token_response.status_code != 200:
        return f'Token request failed: {token_response.text}', 400

    token_json = token_response.json()
    access_token = token_json['access_token']
    headers = {'Authorization': f'Bearer {access_token}'}
    user_response = requests.get(DISCORD_USER_URL, headers=headers)
    if user_response.status_code != 200:
        return 'Failed to get user info', 400
    user_data = user_response.json()
    user_id = user_data['id']
    session['user'] = user_data
    session['access_token'] = access_token
    authenticated_users[user_id] = {
        'access_token': access_token,
        'user_data': user_data
    }
    return redirect('/')
@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')
@bot.event
async def on_ready():
    print(f'{bot.user} としてログインしました！')
    print(f'Bot ID: {bot.user.id}')
    try:
        synced = await bot.tree.sync()
        print(f'Synced {len(synced)} command(s)')
    except Exception as e:
        print(f'Failed to sync commands: {e}')

@bot.tree.command(name='invite_user', description='認証済みユーザーを指定されたサーバーに招待')
async def invite_user(interaction: discord.Interaction, user_id: str, target_guild_id: str = None):
    """認証済みユーザーを指定されたサーバーに招待"""
    if target_guild_id is None:
        target_guild_id = str(interaction.guild.id)
    try:
        target_guild_id = int(target_guild_id)
        target_guild = bot.get_guild(target_guild_id)
        if not target_guild:
            await interaction.response.send_message("❌ 指定されたサーバーが見つからないか、Botがそのサーバーにいません。", ephemeral=True)
            return
        bot_member = target_guild.get_member(bot.user.id)
        if not bot_member or not bot_member.guild_permissions.create_instant_invite:
            await interaction.response.send_message("❌ Botに招待リンク作成権限がありません。", ephemeral=True)
            return
        if user_id not in authenticated_users:
            auth_url = REDIRECT_URI.replace('/callback', '/auth')
            await interaction.response.send_message(f"❌ ユーザーID `{user_id}` は認証されていません。\n認証URL: {auth_url}", ephemeral=True)
            return

        user_info = authenticated_users[user_id]
        access_token = user_info['access_token']
        try:
            invite = await target_guild.text_channels[0].create_invite(
                max_age=3600, 
                max_uses=1,    
                unique=True
            )
            headers = {
                'Authorization': f'Bot {DISCORD_BOT_TOKEN}',
                'Content-Type': 'application/json'
            }

            put_data = {
                'access_token': access_token
            }

            put_url = f'{DISCORD_API_BASE}/guilds/{target_guild_id}/members/{user_id}'
            response = requests.put(put_url, headers=headers, json=put_data)

            if response.status_code == 201:
                await interaction.response.send_message(f"✅ ユーザー `{user_info['user_data']['username']}` を `{target_guild.name}` に正常に招待しました！")
            elif response.status_code == 204:
                await interaction.response.send_message(f"ℹ️ ユーザー `{user_info['user_data']['username']}` は既に `{target_guild.name}` のメンバーです。")
            else:
                await interaction.response.send_message(f"❌ 招待に失敗しました。エラーコード: {response.status_code}", ephemeral=True)
                print(f"Invite error: {response.text}")

        except Exception as e:
            await interaction.response.send_message(f"❌ 招待処理中にエラーが発生しました: {str(e)}", ephemeral=True)
            print(f"Invite error: {e}")
    except ValueError:
        await interaction.response.send_message("❌ 無効なサーバーIDです。", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"❌ エラーが発生しました: {str(e)}", ephemeral=True)

@bot.tree.command(name='auth_status', description='ユーザーの認証状態を確認')
async def auth_status(interaction: discord.Interaction, user_id: str = None):
    """ユーザーの認証状態を確認"""
    if user_id is None:
        user_id = str(interaction.user.id)
    if user_id in authenticated_users:
        user_data = authenticated_users[user_id]['user_data']
        await interaction.response.send_message(f"✅ ユーザー `{user_data['username']}#{user_data['discriminator']}` は認証済みです。")
    else:
        auth_url = REDIRECT_URI.replace('/callback', '/auth')
        await interaction.response.send_message(f"❌ ユーザーID `{user_id}` は認証されていません。\n認証URL: {auth_url}", ephemeral=True)
@bot.tree.command(name='authlink', description='認証リンクボタンを表示')
async def authlink(interaction: discord.Interaction):
    """認証リンクボタンを表示（誰でも使用可能）"""
    embed = discord.Embed(
        title="🔐 Discord OAuth認証",
        description="このBotを使用するには、まずDiscord OAuth認証を完了してください。",
        color=0x5865F2
    )
    base_url = REDIRECT_URI.replace('/callback', '/auth')
    embed.add_field(
        name="📋 手順",
        value="1. 下のボタンをクリック\n2. Discord OAuth認証を完了\n3. `/auth_status` で認証状態を確認",
        inline=False
    )
    class AuthView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=None) 
            url_button = discord.ui.Button(
                label='🔗 認証ページへ', 
                style=discord.ButtonStyle.link, 
                url=base_url
            )
            self.add_item(url_button)
    await interaction.response.send_message(embed=embed, view=AuthView())
@bot.tree.command(name='invite_all_authenticated', description='認証済みメンバー全員を指定されたサーバーに招待')
async def invite_all_authenticated(interaction: discord.Interaction, target_guild_id: str = None):
    """認証済みメンバー全員を指定されたサーバーに招待"""
    # 権限チェック：管理者またはサーバー管理権限
    has_permission = (
        interaction.user.guild_permissions.administrator or
        interaction.user.guild_permissions.manage_guild or
        any(role.name.lower() in ['admin', 'administrator'] for role in interaction.user.roles)
    )
    
    if not has_permission:
        await interaction.response.send_message("❌ このコマンドを使用するには管理者権限が必要です。", ephemeral=True)
        return

    if target_guild_id is None:
        target_guild_id = str(interaction.guild.id)

    try:
        target_guild_id = int(target_guild_id)
        target_guild = bot.get_guild(target_guild_id)
        if not target_guild:
            await interaction.response.send_message("❌ 指定されたサーバーが見つからないか、Botがそのサーバーにいません。", ephemeral=True)
            return

        bot_member = target_guild.get_member(bot.user.id)
        if not bot_member or not bot_member.guild_permissions.create_instant_invite:
            await interaction.response.send_message("❌ Botに招待リンク作成権限がありません。", ephemeral=True)
            return

        if not authenticated_users:
            auth_url = REDIRECT_URI.replace('/callback', '/auth')
            await interaction.response.send_message(f"❌ 認証済みユーザーがいません。\n認証URL: {auth_url}", ephemeral=True)
            return

        await interaction.response.defer()

        success_count = 0
        already_member_count = 0
        error_count = 0
        error_details = []

        for user_id, user_info in authenticated_users.items():
            try:
                access_token = user_info['access_token']
                
                headers = {
                    'Authorization': f'Bot {DISCORD_BOT_TOKEN}',
                    'Content-Type': 'application/json'
                }

                put_data = {
                    'access_token': access_token
                }

                put_url = f'{DISCORD_API_BASE}/guilds/{target_guild_id}/members/{user_id}'
                response = requests.put(put_url, headers=headers, json=put_data)

                if response.status_code == 201:
                    success_count += 1
                elif response.status_code == 204:
                    already_member_count += 1
                else:
                    error_count += 1
                    error_details.append(f"User {user_info['user_data']['username']}: {response.status_code}")

            except Exception as e:
                error_count += 1
                error_details.append(f"User {user_info['user_data']['username']}: {str(e)}")

        result_embed = discord.Embed(
            title="一括招待結果",
            color=0x00ff00 if error_count == 0 else 0xff9900
        )
        
        result_embed.add_field(name="✅ 新規招待", value=success_count, inline=True)
        result_embed.add_field(name="ℹ️ 既存メンバー", value=already_member_count, inline=True)
        result_embed.add_field(name="❌ エラー", value=error_count, inline=True)
        
        if error_details:
            error_text = "\n".join(error_details[:5])  # 最初の5つのエラーのみ表示
            if len(error_details) > 5:
                error_text += f"\n... 他{len(error_details) - 5}件"
            result_embed.add_field(name="エラー詳細", value=error_text, inline=False)

        await interaction.followup.send(embed=result_embed)

    except ValueError:
        await interaction.followup.send("❌ 無効なサーバーIDです。")
    except Exception as e:
        await interaction.followup.send(f"❌ エラーが発生しました: {str(e)}")

@bot.tree.command(name='bot_info', description='Botの情報を表示')
async def bot_info(interaction: discord.Interaction):
    """Botの情報を表示"""
    embed = discord.Embed(
        title="Discord OAuth Bot",
        description="OAuth認証を使用してユーザーをサーバーに招待するBot",
        color=0x5865F2
    )
    auth_url = REDIRECT_URI.replace('/callback', '/auth')
    embed.add_field(name="認証URL", value=auth_url, inline=False)
    embed.add_field(name="コールバックURL", value=REDIRECT_URI, inline=False)
    embed.add_field(name="認証済みユーザー数", value=len(authenticated_users), inline=True)
    embed.add_field(name="サーバー数", value=len(bot.guilds), inline=True)

    await interaction.response.send_message(embed=embed)

@bot.tree.command(name='list_authenticated', description='認証済みユーザーの一覧を表示')
async def list_authenticated(interaction: discord.Interaction):
    """認証済みユーザーの一覧を表示"""
    if not authenticated_users:
        auth_url = REDIRECT_URI.replace('/callback', '/auth')
        await interaction.response.send_message(f"❌ 認証済みユーザーがいません。\n認証URL: {auth_url}", ephemeral=True)
        return

    embed = discord.Embed(
        title="認証済みユーザー一覧",
        description=f"総数: {len(authenticated_users)}人",
        color=0x5865F2
    )

    user_list = []
    for user_id, user_info in list(authenticated_users.items())[:20]:  # 最大20人まで表示
        user_data = user_info['user_data']
        username = user_data.get('username', 'Unknown')
        discriminator = user_data.get('discriminator', '0000')
        if discriminator == '0':  # 新しいDiscordユーザー名形式
            user_list.append(f"`{user_id}` - @{username}")
        else:
            user_list.append(f"`{user_id}` - {username}#{discriminator}")

    if user_list:
        embed.add_field(
            name="ユーザー一覧", 
            value="\n".join(user_list), 
            inline=False
        )

    if len(authenticated_users) > 20:
        embed.set_footer(text=f"... 他{len(authenticated_users) - 20}人")

    await interaction.response.send_message(embed=embed, ephemeral=True)

def run_flask():
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)

def run_bot():
    bot.run(DISCORD_BOT_TOKEN)

if __name__ == '__main__':
    if not all([DISCORD_CLIENT_ID, DISCORD_CLIENT_SECRET, DISCORD_BOT_TOKEN]):
        print("❌ 必要な環境変数が設定されていません:")
        print("- DISCORD_CLIENT_ID")
        print("- DISCORD_CLIENT_SECRET") 
        print("- DISCORD_BOT_TOKEN")
        print("- REDIRECT_URI (オプション)")
        exit(1)
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    port = int(os.environ.get('PORT', 5000))
    print(f"Flask server started on http://0.0.0.0:{port}")
    print("Starting Discord bot...")
    run_bot()
