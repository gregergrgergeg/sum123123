#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import discord
from discord.ext import commands
import os
import re
import requests
import urllib.parse
import logging
import random
import io

# --- Basic Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("account_tracker_bot")

# --- Configuration ---
# IMPORTANT: You MUST create a .env file and add your bot token:
# DISCORD_BOT_TOKEN=YOUR_REAL_BOT_TOKEN_HERE
from dotenv import load_dotenv
load_dotenv()
BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")

# Channel IDs from your request
DATABASE_CHANNEL_ID = 1445810654341759158
COMMANDS_INFO_CHANNEL_ID = 1445810211049836698

# --- Account Status Checking Logic (from your provided script) ---
API_BASE = "https://api.proswapper.xyz/external"
_HEX32 = re.compile(r"^[0-9a-fA-F]{32}$")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*", "Accept-Language": "en-US,en;q=0.9",
}
# Using a few proxies from your list as a fallback
PROXIES = ["45.89.53.245:3128", "66.36.234.130:1339", "45.167.126.1:8080"]

def get_api_response(url, timeout=8.0):
    """Makes a request to the API, trying proxies if direct connection fails."""
    try:
        # First, try a direct connection
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        if resp.status_code in [200, 404]:
            return resp
    except requests.RequestException as e:
        logger.warning(f"Direct connection failed: {e}. Trying proxies.")

    # If direct connection fails, try proxies
    shuffled_proxies = PROXIES.copy()
    random.shuffle(shuffled_proxies)
    for proxy in shuffled_proxies:
        try:
            proxy_url = f'http://{proxy}'
            resp = requests.get(url, headers=HEADERS, proxies={'http': proxy_url, 'https': proxy_url}, timeout=timeout)
            if resp.status_code in [200, 404]:
                logger.info(f"Request successful with proxy: {proxy}")
                return resp
        except requests.RequestException:
            logger.warning(f"Proxy {proxy} failed.")
            continue
            
    logger.error("API request failed completely after trying direct and all proxies.")
    return None

def epic_lookup_by_id(account_id):
    """Looks up an Epic account by its ID."""
    if not account_id or not _HEX32.match(account_id):
        return {"status": "INVALID", "message": "Invalid account ID format."}
    
    response = get_api_response(f"{API_BASE}/id/{account_id}")
    
    if response is None:
        return {"status": "ERROR", "message": "API request failed."}
    if response.status_code == 404:
        return {"status": "INACTIVE", "message": "Account not found or inactive (404)."}
    
    try:
        data = response.json()
        if response.status_code == 200 and data:
            return {"status": "ACTIVE", "data": data}
        return {"status": "INACTIVE", "message": "API returned an empty or invalid response."}
    except Exception:
        return {"status": "ERROR", "message": "Failed to decode the API response."}

# --- Bot Setup ---
intents = discord.Intents.default()
intents.messages = True
intents.guilds = True
intents.message_content = True # Required to read message content

bot = commands.Bot(command_prefix='!', intents=intents)

# --- Helper Functions ---
async def find_account_line_in_attachments(ctx, account_id):
    """Scans recent messages for a .txt attachment and finds the account line."""
    async for message in ctx.channel.history(limit=20):
        if message.attachments:
            for attachment in message.attachments:
                if attachment.filename.endswith('.txt'):
                    try:
                        # Read the attachment content into a string
                        file_content_bytes = await attachment.read()
                        file_content = file_content_bytes.decode('utf-8')
                        
                        # Search for the line containing the AccountID
                        for line in file_content.splitlines():
                            if f"AccountID: {account_id}" in line:
                                return {"line": line, "message": message}
                    except Exception as e:
                        logger.error(f"Failed to read or parse attachment {attachment.filename}: {e}")
                        continue # Try next attachment or message
    return None


async def find_saved_message(database_channel, account_id):
    """Finds a message in the database channel for a given account ID."""
    async for message in database_channel.history(limit=200):
        if message.embeds and message.embeds[0].footer:
            if account_id in message.embeds[0].footer.text:
                return message
    return None

# --- Bot Events ---
@bot.event
async def on_ready():
    """Event for when the bot logs in and is ready."""
    logger.info(f'Logged in as {bot.user.name}')
    logger.info(f'Database Channel ID: {DATABASE_CHANNEL_ID}')
    logger.info(f'Commands Info Channel ID: {COMMANDS_INFO_CHANNEL_ID}')

    # Set custom status
    activity = discord.CustomActivity(name="Smoking on a pack")
    await bot.change_presence(activity=activity)
    
    # Post commands list
    cmd_channel = bot.get_channel(COMMANDS_INFO_CHANNEL_ID)
    if cmd_channel:
        embed = discord.Embed(title="📜 Bot Commands List", color=discord.Color.blue())
        embed.add_field(name="`!s <account_id>`", value="Saves an account by finding it in a recently attached .txt file.", inline=False)
        embed.add_field(name="`!c <account_id>`", value="Checks if an account is saved.", inline=False)
        embed.add_field(name="`!r <account_id>`", value="Removes a saved account.", inline=False)
        embed.add_field(name="`!g <account_id>`", value="Gets the original info for a saved account.", inline=False)
        embed.add_field(name="`!ss <account_id>`", value="Searches API to check if an account is active.", inline=False)
        embed.add_field(name="`!ch <channel_name>`", value="Creates a new text channel (requires 'Manage Channels' permission).", inline=False)
        
        # Clear old command lists and post new one
        await cmd_channel.purge(limit=10, check=lambda msg: msg.author == bot.user)
        await cmd_channel.send(embed=embed)


# --- Bot Commands ---
@bot.command(name='s')
async def save_account(ctx, account_id: str):
    """Saves an account by finding its info in a .txt attachment and posting to the database channel."""
    if not _HEX32.match(account_id):
        return await ctx.reply("❌ **Error:** Invalid Account ID format.")

    db_channel = bot.get_channel(DATABASE_CHANNEL_ID)
    if not db_channel:
        return await ctx.reply("❌ **Error:** Database channel not found.")

    # Check if already saved
    if await find_saved_message(db_channel, account_id):
        return await ctx.reply(f"⚠️ **Notice:** Account `{account_id}` is already saved.")

    # Find the original line from a .txt attachment
    await ctx.reply(f"🔍 Searching recent attachments for `{account_id}`...")
    found_data = await find_account_line_in_attachments(ctx, account_id)
    
    if not found_data:
        return await ctx.message.edit(content=f"❌ **Error:** Could not find `{account_id}` in any recent .txt file attachments.")

    line_to_save = found_data["line"]
    source_message = found_data["message"]

    # Create embed and save to database channel
    embed = discord.Embed(
        title="✅ Account Saved",
        description=f"Found in a file uploaded by {source_message.author.mention}.",
        color=discord.Color.green()
    )
    embed.add_field(name="Original Line", value=f"```{line_to_save}```", inline=False)
    embed.set_footer(text=f"AccountID: {account_id}")
    
    await db_channel.send(embed=embed)
    await ctx.message.edit(content=f"✅ **Success!** Account `{account_id}` has been saved from the attached file.")

@bot.command(name='c')
async def check_account(ctx, account_id: str):
    """Checks if an account is currently saved in the database."""
    if not _HEX32.match(account_id):
        return await ctx.reply("❌ **Error:** Invalid Account ID format.")

    db_channel = bot.get_channel(DATABASE_CHANNEL_ID)
    if not db_channel:
        return await ctx.reply("❌ **Error:** Database channel not found.")

    saved_msg = await find_saved_message(db_channel, account_id)
    if saved_msg:
        await ctx.reply(f"✅ **Found:** Account `{account_id}` is currently saved. You can view it here: {saved_msg.jump_url}")
    else:
        await ctx.reply(f"❌ **Not Found:** Account `{account_id}` has not been sent on.")

@bot.command(name='r')
async def remove_account(ctx, account_id: str):
    """Removes an account from the database, allowing it to be re-saved."""
    if not _HEX32.match(account_id):
        return await ctx.reply("❌ **Error:** Invalid Account ID format.")

    db_channel = bot.get_channel(DATABASE_CHANNEL_ID)
    if not db_channel:
        return await ctx.reply("❌ **Error:** Database channel not found.")

    saved_msg = await find_saved_message(db_channel, account_id)
    if saved_msg:
        await saved_msg.delete()
        await ctx.reply(f"🗑️ **Success!** Account `{account_id}` has been removed. You can now re-send on it.")
    else:
        await ctx.reply(f"❌ **Error:** Account `{account_id}` was not found in the database.")

@bot.command(name='g')
async def get_account_info(ctx, account_id: str):
    """Gets the saved information for an account and replies with it."""
    if not _HEX32.match(account_id):
        return await ctx.reply("❌ **Error:** Invalid Account ID format.")

    db_channel = bot.get_channel(DATABASE_CHANNEL_ID)
    if not db_channel:
        return await ctx.reply("❌ **Error:** Database channel not found.")

    saved_msg = await find_saved_message(db_channel, account_id)
    if saved_msg and saved_msg.embeds:
        # Extract the line from the 'Original Line' field
        original_content = saved_msg.embeds[0].fields[0].value.replace("```", "")
        reply_content = f"**Original Info for Account `{account_id}`:**\n```\n{original_content.strip()}\n```"
        await ctx.reply(reply_content)
    else:
        await ctx.reply(f"❌ **Error:** Could not retrieve info for `{account_id}`. Is it saved?")

@bot.command(name='ss')
async def search_status(ctx, account_id: str):
    """Uses the API to check the live status of an Epic Games account."""
    msg = await ctx.reply(f"🔍 Searching for account status of `{account_id}`...")

    result = epic_lookup_by_id(account_id)
    
    if result["status"] == "ACTIVE":
        account = result["data"]
        # The API gives a list of accounts, we'll take the first one
        account_details = account[0] if isinstance(account, list) else account
        display_name = account_details.get('displayName', 'N/A')
        
        embed = discord.Embed(
            title=f"✅ Account Active: {display_name}", 
            color=discord.Color.green()
        )
        embed.add_field(name="Account ID", value=account_details.get('id', 'N/A'), inline=False)
        
        # Add a direct link to a stats tracker
        tracker_link = f"https://fortnitetracker.com/profile/all/{urllib.parse.quote(display_name)}"
        embed.add_field(name="🔗 Links", value=f"[Fortnite Tracker]({tracker_link})", inline=False)
        
        await msg.edit(content=None, embed=embed)
        
    elif result["status"] == "INACTIVE":
        embed = discord.Embed(title="❌ Account Inactive", description=result.get("message"), color=discord.Color.red())
        await msg.edit(content=None, embed=embed)
        
    else: # ERROR or INVALID
        embed = discord.Embed(title="🚫 Error", description=result.get("message"), color=discord.Color.orange())
        await msg.edit(content=None, embed=embed)

@bot.command(name='ch')
@commands.has_permissions(manage_channels=True)
async def create_channel(ctx, *, channel_name: str):
    """Creates a new text channel. User must have 'Manage Channels' permission."""
    try:
        new_channel = await ctx.guild.create_text_channel(name=channel_name)
        await ctx.reply(f"✅ **Success!** Channel `#{new_channel.name}` has been created.")
    except discord.Forbidden:
        await ctx.reply("❌ **Error:** I don't have the required permissions to create channels.")
    except Exception as e:
        await ctx.reply(f"❌ **An unexpected error occurred:** {e}")

@create_channel.error
async def create_channel_error(ctx, error):
    """Error handler for the create_channel command."""
    if isinstance(error, commands.MissingPermissions):
        await ctx.reply("❌ **Error:** You do not have permission to manage channels.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.reply("❌ **Error:** You must specify a name for the channel. Usage: `!ch <channel_name>`")


# --- Main Execution ---
if __name__ == "__main__":
    if not BOT_TOKEN:
        logger.critical("FATAL: DISCORD_BOT_TOKEN is not set in the environment or .env file.")
    else:
        try:
            bot.run(BOT_TOKEN)
        except discord.errors.LoginFailure:
            logger.critical("FATAL: Login failed. The provided Discord bot token is invalid.")
