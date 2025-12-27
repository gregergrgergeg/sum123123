import discord
from discord.ext import commands
import requests
import json
import os
import time
import datetime
import asyncio

# =================================================================================
#  WARNING: RISK OF EPIC GAMES ACCOUNT BAN
#  Automating gifting and other in-game actions is a violation of the Epic Games
#  Terms of Service. Use this script at your own risk. All accounts involved
#  (gifting and receiving) could be permanently banned without warning.
# =================================================================================

# --- Configuration ---
ACCOUNTS_FILE = "saved_accounts.json"
SF_STATE_FILE = "sf_state.json"
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN") # Get token from environment variables

# API Constants
BASIC_AUTH_HEADER = "basic MzRhMDJjZjhmNDQxNGUyOWIxNTkyMTg3NmRhMzZmOWE6ZGFhZmJkYmY3Mzc0NDUwOWE2ZTgyMmY3YjMxM2M3MmM="
TOKEN_URL = "https://account-public-service-prod.ol.epicgames.com/account/api/oauth/token"
FRIENDS_API_URL = "https://friends-public-service-prod.ol.epicgames.com/friends/api/v1/{account_id}/friends/{target_account_id}"
ITEM_SHOP_URL = "https://fortnite-public-service-prod11.ol.epicgames.com/fortnite/api/storefront/v2/catalog"
GIFT_API_URL = "https://fortnite-public-service-prod11.ol.epicgames.com/fortnite/api/game/v2/profile/{account_id}/client/GiftCatalogEntry"

# --- Bot Setup ---
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# --- CORE API & HELPER FUNCTIONS ---

def load_json(filename):
    if not os.path.exists(filename):
        return {}
    try:
        with open(filename, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}

def save_json(data, filename):
    try:
        with open(filename, 'w') as f:
            json.dump(data, f, indent=4)
        return True
    except IOError:
        return False

async def refresh_access_token(account):
    headers = {'Authorization': BASIC_AUTH_HEADER, 'Content-Type': 'application/x-www-form-urlencoded'}
    data = {'grant_type': 'refresh_token', 'refresh_token': account['refresh_token']}
    
    response = requests.post(TOKEN_URL, headers=headers, data=data)
    
    if response.status_code == 200:
        token_data = response.json()
        account['access_token'] = token_data['access_token']
        account['refresh_token'] = token_data['refresh_token']
        # Update accounts file
        all_accounts = load_json(ACCOUNTS_FILE)
        for i, acc in enumerate(all_accounts):
            if acc['account_id'] == account['account_id']:
                all_accounts[i] = account
                break
        save_json(all_accounts, ACCOUNTS_FILE)
        return account, None
    else:
        error_message = f"Failed to refresh token for {account['displayName']}. Status: {response.status_code}. It may need re-authentication."
        return None, error_message

def get_auth_headers(access_token):
    return {'Authorization': f'bearer {access_token}', 'Content-Type': 'application/json'}

async def get_item_shop(account):
    # This function would be expanded to get the full item shop
    # For now, it's a placeholder
    return {"daily_emotes": [{"id": "eid_dancetherapy", "price": 800}]}

async def check_user_has_item(account, target_user_id, item_id):
    # CRITICAL NOTE: There is no public/reliable Epic Games API to check another user's locker.
    # This is a major roadblock for the "don't gift duplicates" feature.
    # This function is a placeholder and assumes the user does NOT have the item.
    # In a real-world scenario, you might have to track gifted items manually in your sf_state.json.
    return False

async def gift_item(account, target_user_id, item_id):
    # Placeholder for the complex gifting logic
    # In reality, this would involve a multi-step profile query and command
    print(f"SIMULATING: Gifting item {item_id} from {account['displayName']} to {target_user_id}")
    return True, "Gift successful (simulation)"

async def get_vbucks_balance(account):
    # Placeholder for fetching V-Bucks balance
    # This would typically be part of a larger "QueryProfile" call
    return 1000 # Return a mock value for testing

# --- BACKGROUND !SF LOGIC ---

async def sf_logic(ctx, target_username):
    """The main background task for the !sf command."""
    await ctx.send(f"**`!sf` Background Task Started**\nTargeting user: `{target_username}`")

    accounts = load_json(ACCOUNTS_FILE)
    if not accounts:
        await ctx.send("Error: `accounts.json` not found or is empty. Please add accounts first.")
        return

    # For this example, we'll assume the target_username is their Epic ID.
    # A real implementation would need to look up the account ID from the username.
    target_user_id = f"epic_id_for_{target_username}"

    # For simplicity, we'll skip the "Add Friend" and 3-day wait logic in this example.
    # A real implementation would need to manage this state.
    await ctx.send("Friend request and 3-day wait period are being simulated for this test.")

    # --- Main Gifting Loop ---
    # This loop would be run on a schedule (e.g., daily) in a real application.
    await ctx.send("--- Starting Gifting Cycle ---")
    
    # 1. Get the item shop
    shop_data = await get_item_shop(accounts[0]) # Use first account to check the shop
    emotes_to_gift = shop_data.get('daily_emotes', [])

    if not emotes_to_gift:
        await ctx.send("No emotes found in the item shop today.")
        return

    for emote in emotes_to_gift:
        emote_id = emote['id']
        emote_price = emote['price']
        
        await ctx.send(f"Checking emote `{emote_id}` (Price: {emote_price} V-Bucks)...")

        # 2. Check if target already has the item
        already_owned = await check_user_has_item(accounts[0], target_user_id, emote_id)
        if already_owned:
            await ctx.send(f"-> Target already owns `{emote_id}`. Skipping.")
            continue

        # 3. Find an account to gift from
        gift_sent = False
        for account in accounts:
            refreshed_account, error = await refresh_access_token(account)
            if error:
                await ctx.send(f"-> Skipping account `{account['displayName']}`: {error}")
                continue

            vbucks = await get_vbucks_balance(refreshed_account)
            if vbucks >= emote_price:
                await ctx.send(f"-> Attempting to gift `{emote_id}` from `{refreshed_account['displayName']}` ({vbucks} V-Bucks)...")
                success, message = await gift_item(refreshed_account, target_user_id, emote_id)
                await ctx.send(f"--> {message}")
                if success:
                    gift_sent = True
                    break # Stop trying to gift this emote, move to the next one
            else:
                await ctx.send(f"-> Insufficient V-Bucks in `{refreshed_account['displayName']}` ({vbucks} V-Bucks).")

        if not gift_sent:
            await ctx.send(f"Could not gift emote `{emote_id}`. No available account had enough V-Bucks.")

    await ctx.send("\n**`!sf` Gifting Cycle Complete**")


# --- DISCORD COMMANDS ---

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name}')
    print('Bot is ready to receive commands.')

@bot.command(name='sf')
async def sf_command(ctx, target_username: str = None):
    """
    Starts the automated emote gifting service for a target user.
    Usage: !sf <EpicGamesUsername>
    """
    if not target_username:
        await ctx.send("Please provide the Epic Games username of the person you want to gift to.\n**Usage:** `!sf TheTargetPlayer`")
        return

    # Acknowledge the command immediately
    await ctx.send(f"✅ **`!sf` command received for `{target_username}`.**\nStarting the gifting process in the background. I will post updates in this channel.")
    
    # Start the long-running logic as a background task
    asyncio.create_task(sf_logic(ctx, target_username))

# --- RUN THE BOT ---
if __name__ == "__main__":
    if DISCORD_BOT_TOKEN:
        bot.run(DISCORD_BOT_TOKEN)
    else:
        print("Error: DISCORD_BOT_TOKEN environment variable not found.")
        print("Please set it in your hosting service (e.g., Render) or a .env file.")
