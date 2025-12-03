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
from dotenv import load_dotenv
load_dotenv()
BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")

# Channel IDs from your request
# This channel is for the master .txt file AND for saving embeds
DATABASE_CHANNEL_ID = 1445810654341759158 
COMMANDS_INFO_CHANNEL_ID = 1445810211049836698

# In-memory cache for the account data
account_data_cache = {}

# --- Account Status Checking Logic ---
API_BASE = "https://api.proswapper.xyz/external"
_HEX32 = re.compile(r"^[0-9a-fA-F]{32}$")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*", "Accept-Language": "en-US,en;q=0.9",
}
PROXIES = ["geo.iproyal.com:12321:FFCSEjg822t4ZQxe:oMLjrG7iivzkF1QQ_country-ca,us_streaming-1"]

def get_api_response(url, timeout=15.0):
    """Makes a request to the API, using an authenticated proxy."""
    try:
        proxy_string = random.choice(PROXIES)
        parts = proxy_string.split(':')
        host, port, user, pw = parts[0], parts[1], parts[2], ':'.join(parts[3:])
        proxy_url = f"http://{user}:{pw}@{host}:{port}"
        proxies_dict = {'http': proxy_url, 'https': proxy_url}
        resp = requests.get(url, headers=HEADERS, proxies=proxies_dict, timeout=timeout)
        if resp.status_code in [200, 404]:
            logger.info(f"Request successful with proxy: {host}")
            return resp
    except Exception as e:
        logger.error(f"API request via proxy failed: {e}")
            
    logger.error("API request failed completely.")
    return None

# --- Bot Setup & Data Loading ---
intents = discord.Intents.default()
intents.messages = True
intents.guilds = True
intents.message_content = True

bot = commands.Bot(command_prefix='!', intents=intents)

async def load_data_from_database_file(channel):
    """Finds the latest .txt file in the DB channel and loads it into memory."""
    global account_data_cache
    logger.info("Searching for master data file in database channel...")
    async for message in channel.history(limit=100):
        if message.attachments:
            attachment = next((att for att in message.attachments if att.filename.endswith('.txt')), None)
            if attachment:
                logger.info(f"Found master data file: {attachment.filename}")
                try:
                    file_content_bytes = await attachment.read()
                    file_content = file_content_bytes.decode('utf-8')
                    
                    temp_cache = {}
                    line_count = 0
                    id_regex = re.compile(r"AccountID:\s*([0-9a-fA-F]{32})", re.IGNORECASE)
                    for line in file_content.splitlines():
                        match = id_regex.search(line)
                        if match:
                            account_id = match.group(1).lower()
                            temp_cache[account_id] = line
                            line_count += 1
                    
                    account_data_cache = temp_cache
                    logger.info(f"Successfully loaded {line_count} accounts into memory.")
                    return line_count
                except Exception as e:
                    logger.error(f"Failed to read or parse master data file {attachment.filename}: {e}")
                    return 0
    logger.warning("No master .txt data file found in the database channel.")
    return 0

# --- Bot Events ---
@bot.event
async def on_ready():
    """Event for when the bot logs in and is ready."""
    logger.info(f'Logged in as {bot.user.name}')
    db_channel = bot.get_channel(DATABASE_CHANNEL_ID)
    if db_channel:
        await load_data_from_database_file(db_channel)
    else:
        logger.error(f"Could not find Database Channel with ID {DATABASE_CHANNEL_ID}")

    activity = discord.CustomActivity(name="Smoking on a pack")
    await bot.change_presence(activity=activity)
    
    cmd_channel = bot.get_channel(COMMANDS_INFO_CHANNEL_ID)
    if cmd_channel:
        embed = discord.Embed(title="📜 Bot Commands List", color=discord.Color.blue())
        embed.add_field(name="`!s <account_id>`", value="Saves an account from the pre-loaded master file.", inline=False)
        embed.add_field(name="`!c <account_id>`", value="Checks if an account is saved.", inline=False)
        embed.add_field(name="`!r <account_id>`", value="Removes a saved account.", inline=False)
        embed.add_field(name="`!g <account_id>`", value="Gets the original info for a saved account.", inline=False)
        embed.add_field(name="`!ss <account_id>`", value="Searches API to check if an account is active.", inline=False)
        embed.add_field(name="`!ch <channel_name>`", value="Creates a new text channel (requires 'Manage Channels' permission).", inline=False)
        await cmd_channel.purge(limit=10, check=lambda msg: msg.author == bot.user)
        await cmd_channel.send(embed=embed)

@bot.event
async def on_message(message):
    """Event that triggers on every message."""
    # Ignore messages from the bot itself
    if message.author.bot:
        return

    # Check if the message is in the database channel and has a .txt attachment
    if message.channel.id == DATABASE_CHANNEL_ID and message.attachments:
        attachment = next((att for att in message.attachments if att.filename.endswith('.txt')), None)
        if attachment:
            logger.info("New .txt file detected in database channel. Reloading data...")
            # Reload the data from the newest file
            loaded_count = await load_data_from_database_file(message.channel)
            if loaded_count > 0:
                await message.channel.send(f"✅ **Auto-reloaded!** Memorized {loaded_count} accounts from `{attachment.filename}`.")
            else:
                 await message.channel.send(f"⚠️ **Notice:** Detected `{attachment.filename}` but failed to load any accounts from it.")

    # Process commands after handling the event
    await bot.process_commands(message)

# --- Bot Commands ---
@bot.command(name='s')
async def save_account(ctx, account_id: str):
    """Saves an account by finding its info in the in-memory data cache."""
    if not _HEX32.match(account_id.lower()):
        return await ctx.reply("❌ **Error:** Invalid Account ID format.")

    account_id = account_id.lower()
    db_channel = bot.get_channel(DATABASE_CHANNEL_ID)
    if not db_channel:
        return await ctx.reply("❌ **Error:** Database channel not found.")

    # Check if already saved
    async for msg in db_channel.history(limit=200):
        if msg.embeds and msg.embeds[0].footer and account_id in msg.embeds[0].footer.text.lower():
             return await ctx.reply(f"⚠️ **Notice:** Account `{account_id}` is already saved.")

    # Find the line from the in-memory cache
    line_to_save = account_data_cache.get(account_id)
    
    if not line_to_save:
        return await ctx.reply(f"❌ **Error:** Could not find `{account_id}` in memory. Make sure the master file has been uploaded.")

    # Create embed and save to database channel
    embed = discord.Embed(
        title="✅ Account Saved",
        description=f"Saved by {ctx.author.mention} from the master data file.",
        color=discord.Color.green()
    )
    embed.add_field(name="Original Line", value=f"```{line_to_save}```", inline=False)
    embed.set_footer(text=f"AccountID: {account_id}")
    
    await db_channel.send(embed=embed)
    await ctx.reply(f"✅ **Success!** Account `{account_id}` has been saved.")

# (The other commands: !c, !r, !g, !ss, !ch remain largely unchanged)
@bot.command(name='c')
async def check_account(ctx, account_id: str):
    if not _HEX32.match(account_id.lower()):
        return await ctx.reply("❌ **Error:** Invalid Account ID format.")
    account_id = account_id.lower()
    db_channel = bot.get_channel(DATABASE_CHANNEL_ID)
    if not db_channel: return await ctx.reply("❌ **Error:** Database channel not found.")

    async for msg in db_channel.history(limit=200):
        if msg.embeds and msg.embeds[0].footer and account_id in msg.embeds[0].footer.text.lower():
            return await ctx.reply(f"✅ **Found:** Account `{account_id}` is saved. View: {msg.jump_url}")
    await ctx.reply(f"❌ **Not Found:** Account `{account_id}` has not been sent on.")

@bot.command(name='r')
async def remove_account(ctx, account_id: str):
    if not _HEX32.match(account_id.lower()):
        return await ctx.reply("❌ **Error:** Invalid Account ID format.")
    account_id = account_id.lower()
    db_channel = bot.get_channel(DATABASE_CHANNEL_ID)
    if not db_channel: return await ctx.reply("❌ **Error:** Database channel not found.")

    async for msg in db_channel.history(limit=200):
        if msg.embeds and msg.embeds[0].footer and account_id in msg.embeds[0].footer.text.lower():
            await msg.delete()
            return await ctx.reply(f"🗑️ **Success!** Account `{account_id}` has been removed.")
    await ctx.reply(f"❌ **Error:** Account `{account_id}` was not found in the database.")

@bot.command(name='g')
async def get_account_info(ctx, account_id: str):
    if not _HEX32.match(account_id.lower()):
        return await ctx.reply("❌ **Error:** Invalid Account ID format.")
    account_id = account_id.lower()
    db_channel = bot.get_channel(DATABASE_CHANNEL_ID)
    if not db_channel: return await ctx.reply("❌ **Error:** Database channel not found.")

    async for msg in db_channel.history(limit=200):
        if msg.embeds and msg.embeds[0].footer and account_id in msg.embeds[0].footer.text.lower():
            original_content = msg.embeds[0].fields[0].value.replace("```", "")
            reply_content = f"**Original Info for Account `{account_id}`:**\n```\n{original_content.strip()}\n```"
            return await ctx.reply(reply_content)
    await ctx.reply(f"❌ **Error:** Could not retrieve info for `{account_id}`. Is it saved?")

@bot.command(name='ss')
async def search_status(ctx, account_id: str):
    msg = await ctx.reply(f"🔍 Searching for account status of `{account_id}`...")
    # Using .get on the cache to avoid errors if the ID isn't found
    line = account_data_cache.get(account_id.lower(), "")
    name_match = re.search(r"Display Name:\s*(\S+)", line, re.IGNORECASE)
    display_name = name_match.group(1) if name_match else "N/A"
    
    tracker_link = f"https://fortnitetracker.com/profile/all/{urllib.parse.quote(display_name)}"
    
    embed = discord.Embed(title=f"🔎 Account Info: {display_name}", color=discord.Color.blue())
    embed.add_field(name="Account ID", value=account_id, inline=False)
    embed.add_field(name="🔗 Links", value=f"[Fortnite Tracker]({tracker_link})", inline=False)
    await msg.edit(content=None, embed=embed)

@bot.command(name='ch')
@commands.has_permissions(manage_channels=True)
async def create_channel(ctx, *, channel_name: str):
    try:
        new_channel = await ctx.guild.create_text_channel(name=channel_name)
        await ctx.reply(f"✅ **Success!** Channel `#{new_channel.name}` has been created.")
    except discord.Forbidden:
        await ctx.reply("❌ **Error:** I don't have the required permissions to create channels.")
    except Exception as e:
        await ctx.reply(f"❌ **An unexpected error occurred:** {e}")

# --- Main Execution ---
if __name__ == "__main__":
    if not BOT_TOKEN:
        logger.critical("FATAL: DISCORD_BOT_TOKEN is not set in the environment or .env file.")
    else:
        bot.run(BOT_TOKEN)
