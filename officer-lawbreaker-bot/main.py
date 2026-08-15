"""Entry point. Run with `py main.py` (Windows) or `python3 main.py` after
activating the venv - see README.md for the full setup.
"""

import asyncio
import os

import discord
from discord.ext import commands
from dotenv import load_dotenv

from game.cog import OfficerLawbreakerCog

# 1. IMPORT IT HERE (at the top with other imports)
from keep_alive import keep_alive

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.message_content = True  # required: tasks are checked against ordinary chat, not just slash commands
intents.members = True  # required: resolving display names / DM-ing roles reliably

bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready() -> None:
    print(f"Logged in as {bot.user} ({bot.user.id})")
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} slash command(s).")
    except discord.HTTPException as exc:
        print(f"Slash command sync failed: {exc}")


async def main() -> None:
    async with bot:
        await bot.add_cog(OfficerLawbreakerCog(bot))
        await bot.start(TOKEN)


if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit(
            "DISCORD_TOKEN is not set. Copy .env.example to .env and paste your "
            "bot token in, then run this again."
        )
    # 2. Start the web server here
    keep_alive()

    asyncio.run(main())
