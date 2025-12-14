#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import discord
from discord.ext import commands, tasks
import os
import re
import requests
import urllib.parse
import logging
import random
import io
import asyncio
import json

# --- Basic Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("account_tracker_bot")

# -----------------------------------------------------------------------------
# --- CONFIGURATION ---
# Fill in all the placeholder values below with your actual information.
# -----------------------------------------------------------------------------

# --- Discord Bot Configuration ---
# Your bot's token from the Discord Developer Portal
DISCORD_BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"

# --- Channel & User IDs ---
# The ID of the channel where you upload the master .txt file
DATABASE_CHANNEL_ID = 123456789012345678
# The ID of the channel where the bot posts its command list
COMMANDS_INFO_CHANNEL_ID = 123456789012345678

# --- Epic Games Tracker ---
# The user ID of the person who should receive the status update DMs
EPIC_TRACK_USER_ID = 851862667823415347

# --- Proswapper API Proxies ---
# A list of your proxies.
# Example: ["user:pass@host:port", "user2:pass2@host2:port"]
PROXIES = ["geo.iproyal.com:12321:FFCSEjg822t4ZQxe:oMLjrG7iivzkF1QQ_country-ca,us_streaming-1"]

# -----------------------------------------------------------------------------
# --- END OF CONFIGURATION ---
# -----------------------------------------------------------------------------


# --- In-memory Caches ---
account_data_cache = {}
tracking_tasks = {} # Stores active Epic Games tracking tasks

# --- API & Header Definitions ---
_HEX32 = re.compile(r"^[0-9a-fA-F]{32}$")

EPIC_API_URL = "https://www.epicgames.com/help/api/account-recovery/status"
# MODIFIED: Headers for the Epic Games request. Cookie is no longer needed.
EPIC_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json;charset=utf-8",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36",
    "Origin": "https://www.epicgames.com",
    "Referer": "https://www.epicgames.com/help/en-US/recovery-status-check",
}

PROSWAPPER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*", "Accept-Language": "en-US,en;q=0.9",
}

# --- Proswapper API Logic ---
def get_api_response(url, timeout=15.0):
    """Makes a request to the proswapper API, using an authenticated proxy."""
    if not PROXIES:
        logger.error("Proxy list is empty. Cannot make API request.")
        return None
    try:
        proxy_string = random.choice(PROXIES)
        parts = proxy_string.split(':')
        host, port, user, pw = parts[0], int(parts[1]), parts[2], ':'.join(parts[3:])
        proxy_url = f"http://{user}:{pw}@{host}:{port}"
        proxies_dict = {'http': proxy_url, 'https': proxy_url}
        resp = requests.get(url, headers=PROSWAPPER_HEADERS, proxies=proxies_dict, timeout=timeout)
        if resp.status_code in [200, 404]:
            logger.info(f"Proswapper request successful with proxy: {host}")
            return resp
    except Exception as e:
        logger.error(f"Proswapper API request via proxy failed: {e}")
    return None

# --- Epic Games Tracking Logic ---
def get_epic_status_meaning(status):
    """Interprets the Epic Games status based on your definition."""
    status_lower = (status or "").lower()
    if "denied" in status_lower: return "Good"
    if "recover" in status_lower or "appeal_in_progress" in status_lower: return "Bad"
    return "Unknown"

# MODIFIED: This task now runs without needing any cookie.
async def track_epic_status(bot, recovery_id):
    """Background task to check Epic Games status and DM on change."""
    last_status = None
    try:
        target_user = await bot.fetch_user(EPIC_TRACK_USER_ID)
    except discord.NotFound:
        logger.error(f"Could not find the user to DM with ID {EPIC_TRACK_USER_ID}. Stopping task.")
        return

    while True:
        try:
            payload = {"recoveryId": recovery_id}
            response = requests.post(EPIC_API_URL, headers=EPIC_HEADERS, json=payload, timeout=20)
            
            if response.status_code == 200:
                current_data = response.json()
                current_status = current_data.get("currentRecovery", {}).get("aggregatedStatus")
                
                if current_status != last_status:
                    logger.info(f"Epic status change for {recovery_id}: from '{last_status}' to '{current_status}'")
                    status_meaning = get_epic_status_meaning(current_status)
                    embed = discord.Embed(title="Epic Games Account Recovery Update", description=f"Status for ticket `{recovery_id}` has changed.", color=discord.Color.orange())
                    embed.add_field(name="New Status", value=f"`{current_status}`", inline=False)
                    embed.add_field(name="Meaning", value=f"**{status_meaning}**", inline=False)
                    await target_user.send(embed=embed)
                    last_status = current_status
            else:
                 logger.error(f"Epic API returned status {response.status_code}. It might require a cookie again in the future.")
                 # No need to stop the task, just log the error and it will retry in an hour.

        except requests.RequestException as e:
            logger.error(f"Request failed for Epic Games tracker: {e}")
        except Exception as e:
            logger.error(f"An unexpected error occurred in the tracking task for {recovery_id}: {e}")

        await asyncio.sleep(3600)  # Wait for 1 hour

    if recovery_id in tracking_tasks:
        del tracking_tasks[recovery_id]

# --- Bot Setup & Data Loading ---
intents = discord.Intents.default()
intents.messages = True
intents.guilds = True
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

async def load_data_from_database_file(channel):
    # This function is unchanged
    global account_data_cache
    logger.info("Searching for master data file in database channel...")
    async for message in channel.history(limit=100):
        if message.attachments:
            attachment = next((att for att in message.attachments if att.filename.endswith('.txt')), None)
            if attachment:
                try:
                    file_content = await attachment.read()
                    temp_cache, id_regex = {}, re.compile(r"AccountID:\s*([0-9a-fA-F]{32})", re.IGNORECASE)
                    for block in file_content.decode('utf-8').split('----------------------------------------'):
                        if match := id_regex.search(block):
                            temp_cache[match.group(1).lower()] = block.strip()
                    account_data_cache = temp_cache
                    logger.info(f"Successfully loaded {len(temp_cache)} accounts from {attachment.filename}.")
                    return len(temp_cache)
                except Exception as e:
                    logger.error(f"Failed to parse master data file {attachment.filename}: {e}")
    return 0
    
# --- Bot Events & Commands ---
@bot.event
async def on_ready():
    logger.info(f'Logged in as {bot.user.name}')
    db_channel = bot.get_channel(DATABASE_CHANNEL_ID)
    if db_channel: await load_data_from_database_file(db_channel)
    cmd_channel = bot.get_channel(COMMANDS_INFO_CHANNEL_ID)
    if cmd_channel:
        embed = discord.Embed(title="📜 Bot Commands List", color=discord.Color.blue())
        embed.add_field(name="`!s <account_id>`", value="Saves an account from the master file.", inline=False)
        embed.add_field(name="`!c <account_id>`", value="Checks if an account is saved.", inline=False)
        embed.add_field(name="`!r <account_id>`", value="Removes a saved account.", inline=False)
        embed.add_field(name="`!g <account_id>`", value="Gets full info for a saved account.", inline=False)
        embed.add_field(name="`!ss <account_id>`", value="Gets a Fortnite Tracker link.", inline=False)
        embed.add_field(name="`!track <recovery_id>`", value="Tracks an Epic recovery ticket.", inline=False)
        embed.add_field(name="`!stoptrack <recovery_id>`", value="Stops tracking a recovery ticket.", inline=False)
        await cmd_channel.purge(limit=10, check=lambda msg: msg.author == bot.user)
        await cmd_channel.send(embed=embed)

# (All other commands: !s, !g, !c, !r, !ss, !ch, file_upload_listener are unchanged and included below)
@bot.listen('on_message')
async def file_upload_listener(message):
    if message.author.bot or message.channel.id != DATABASE_CHANNEL_ID or not message.attachments: return
    if attachment := next((att for att in message.attachments if att.filename.endswith('.txt')), None):
        count = await load_data_from_database_file(message.channel)
        await message.channel.send(f"✅ **Auto-reloaded!** Memorized {count} accounts." if count > 0 else "⚠️ **Notice:** Failed to load accounts.")

@bot.command(name='track')
async def track_command(ctx, recovery_id: str):
    if recovery_id in tracking_tasks: return await ctx.reply("⚠️ Already tracking this ID.")
    task = asyncio.create_task(track_epic_status(bot, recovery_id))
    tracking_tasks[recovery_id] = task
    await ctx.reply(f"✅ **Now Tracking:** I will monitor `{recovery_id}`.")

@bot.command(name='stoptrack')
async def stoptrack_command(ctx, recovery_id: str):
    if not (task := tracking_tasks.get(recovery_id)): return await ctx.reply("❌ Not tracking this ID.")
    task.cancel()
    del tracking_tasks[recovery_id]
    await ctx.reply(f"🛑 **Stopped:** No longer tracking `{recovery_id}`.")
    
@bot.command(name='s')
async def save_account(ctx, account_id: str):
    if not _HEX32.match(account_id.lower()): return await ctx.reply("❌ Invalid ID format.")
    account_id = account_id.lower()
    db_channel = bot.get_channel(DATABASE_CHANNEL_ID)
    async for msg in db_channel.history(limit=200):
        if msg.embeds and msg.embeds[0].footer and account_id in msg.embeds[0].footer.text.lower():
            return await ctx.reply(f"⚠️ Account `{account_id}` is already saved.")
    if not (account_block := account_data_cache.get(account_id)):
        return await ctx.reply(f"❌ Could not find `{account_id}` in memory.")
    original_line = next((line for line in account_block.splitlines() if "AccountID:" in line), "")
    embed = discord.Embed(title="✅ Account Saved", description=f"Saved by {ctx.author.mention}", color=discord.Color.green())
    embed.add_field(name="Original Line", value=f"```{original_line}```", inline=False)
    embed.set_footer(text=f"AccountID: {account_id}")
    await db_channel.send(embed=embed)
    await ctx.reply(f"✅ Saved `{account_id}`.")

@bot.command(name='g')
async def get_account_info(ctx, account_id: str):
    if not _HEX32.match(account_id.lower()): return await ctx.reply("❌ Invalid ID format.")
    if account_block := account_data_cache.get(account_id.lower()):
        return await ctx.reply(f"**Info for `{account_id}`:**\n```\n{account_block}\n```")
    await ctx.reply(f"❌ Could not find info for `{account_id}`.")

@bot.command(name='c')
async def check_account(ctx, account_id: str):
    if not _HEX32.match(account_id.lower()): return await ctx.reply("❌ Invalid ID format.")
    db_channel = bot.get_channel(DATABASE_CHANNEL_ID)
    async for msg in db_channel.history(limit=200):
        if msg.embeds and msg.embeds[0].footer and account_id.lower() in msg.embeds[0].footer.text.lower():
            return await ctx.reply(f"✅ Account `{account_id}` has already been sent on.")
    await ctx.reply(f"❌ Account `{account_id}` has not been sent on.")

@bot.command(name='r')
async def remove_account(ctx, account_id: str):
    if not _HEX32.match(account_id.lower()): return await ctx.reply("❌ Invalid ID format.")
    db_channel = bot.get_channel(DATABASE_CHANNEL_ID)
    async for msg in db_channel.history(limit=200):
        if msg.embeds and msg.embeds[0].footer and account_id.lower() in msg.embeds[0].footer.text.lower():
            await msg.delete()
            return await ctx.reply(f"🗑️ Removed `{account_id}`.")
    await ctx.reply(f"❌ Could not find `{account_id}` to remove.")

@bot.command(name='ss')
async def search_status(ctx, account_id: str):
    line = account_data_cache.get(account_id.lower(), "")
    display_name = (re.search(r"Display Name:\s*(\S+)", line, re.IGNORECASE) or {}).get(1, "N/A")
    tracker_link = f"https://fortnitetracker.com/profile/all/{urllib.parse.quote(display_name)}"
    embed = discord.Embed(title=f"🔎 Account Info: {display_name}", color=discord.Color.blue())
    embed.add_field(name="Account ID", value=account_id, inline=False)
    embed.add_field(name="🔗 Links", value=f"[Fortnite Tracker]({tracker_link})", inline=False)
    await ctx.reply(embed=embed)

@bot.command(name='ch')
@commands.has_permissions(manage_channels=True)
async def create_channel(ctx, *, channel_name: str):
    try:
        new_channel = await ctx.guild.create_text_channel(name=channel_name)
        await ctx.reply(f"✅ Channel `#{new_channel.name}` has been created.")
    except discord.Forbidden:
        await ctx.reply("❌ I don't have permission to create channels.")
    except Exception as e:
        await ctx.reply(f"❌ An error occurred: {e}")

# --- Main Execution ---
if __name__ == "__main__":
    if "YOUR_BOT_TOKEN" in DISCORD_BOT_TOKEN or not DISCORD_BOT_TOKEN:
        logger.critical("FATAL: DISCORD_BOT_TOKEN is not set in the configuration section.")
    else:
        bot.run(DISCORD_BOT_TOKEN)
