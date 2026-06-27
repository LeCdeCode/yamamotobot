import os
import logging
from pathlib import Path

import discord
from discord.ext import commands
from dotenv import load_dotenv
import asyncio
from aiohttp import web

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("divisionmanagerbot")

load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")

BOT_TOKEN = (
    os.getenv("BOT_TOKEN")
    or os.getenv("DISCORD_TOKEN")
    or os.getenv("TOKEN")
)
if not BOT_TOKEN:
    raise RuntimeError(
        "Le jeton du bot est manquant. Ajoute BOT_TOKEN dans les variables d'environnement."
    )

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="d!", intents=intents, help_command=None)


@bot.event
async def on_ready() -> None:
    logger.info("Bot connecté en tant que %s", bot.user)
    logger.info("Serveurs : %s", ", ".join(guild.name for guild in bot.guilds))
    await bot.tree.sync()


@bot.event
async def on_command_error(ctx: commands.Context, error: commands.CommandError) -> None:
    if isinstance(error, commands.CommandNotFound):
        return  # Ignorer silencieusement les commandes inconnues
    elif isinstance(error, commands.CommandOnCooldown):
        await ctx.reply(f"⏳ Commande en recharge. Réessaie dans {error.retry_after:.1f}s.", delete_after=5)
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.reply(f"⚠️ Argument manquant : `{error.param.name}`. Utilise `d!help {ctx.command.name}` pour voir l'usage.", delete_after=8)
    elif isinstance(error, commands.NoPrivateMessage):
        await ctx.reply("⚠️ Cette commande fonctionne uniquement sur le serveur.", delete_after=5)
    elif isinstance(error, commands.MemberNotFound):
        await ctx.reply("⚠️ Membre introuvable. Mentionne un membre valide.", delete_after=5)
    elif isinstance(error, commands.CheckFailure):
        pass  # Géré par chaque cog individuellement
    else:
        logger.exception("Erreur non gérée dans la commande %s", ctx.command)
        await ctx.reply("❌ Une erreur interne est survenue.", delete_after=5)


async def load_extensions() -> None:
    extensions = [
        "cogs.recruitment",
        "cogs.ranking",
        "cogs.division_manager",
        "cogs.help",
        "cogs.config",
        "cogs.profile",
    ]
    for extension_name in extensions:
        try:
            await bot.load_extension(extension_name)
            logger.info("Extension chargée : %s", extension_name)
        except Exception:
            logger.exception("Impossible de charger l'extension %s", extension_name)


async def main_async() -> None:
    await load_extensions()

    keep_alive = os.getenv("KEEP_ALIVE", "false").lower() in ("1", "true", "yes")
    if keep_alive:
        async def _handle(request):
            return web.Response(text="ok")

        async def start_webserver():
            port = int(os.getenv("PORT", 8080))
            app = web.Application()
            app.add_routes([web.get("/", _handle)])
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, "0.0.0.0", port)
            await site.start()
            logger.info("Keep-alive webserver démarré sur le port %s", port)

        asyncio.create_task(start_webserver())

    await bot.start(BOT_TOKEN)


if __name__ == "__main__":
    asyncio.run(main_async())
