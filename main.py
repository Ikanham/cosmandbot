import os
import sys
import asyncio
import logging
from dotenv import load_dotenv
import discord
from discord.ext import commands
from db import close_pool

load_dotenv()

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("CosmandBot")

INITIAL_EXTENSIONS = [
    "cogs.admin",
    "cogs.countdowns",
    "cogs.scheduler",
    "cogs.welcome_goodbye",
    "cogs.help",
    "cogs.errors",
    "cogs.anniversaires",
    "cogs.settings",
    "cogs.say",
    "cogs.logs",
    "cogs.events",
    "cogs.conventions",
]


class CosmandBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        intents.guilds = True
        intents.voice_states = True
        super().__init__(
            command_prefix="+",
            intents=intents,
            help_command=None,
        )

    async def setup_hook(self):
        """Initialise les extensions et tâches avant la connexion au Gateway Discord."""
        logger.info("Vérification et initialisation des index de base de données...")
        try:
            from db import init_db_indexes
            await init_db_indexes()
        except Exception as e:
            logger.warning(f"Impossible d'initialiser les index BDD : {e}")

        logger.info("Chargement initial des extensions...")
        for ext in INITIAL_EXTENSIONS:
            try:
                await self.load_extension(ext)
                logger.info(f"✅ Extension chargée : {ext}")
            except Exception as e:
                logger.exception(f"❌ Échec du chargement de {ext} : {e}")

    async def close(self):
        """Nettoie proprement les ressources lors de l'arrêt du bot."""
        logger.info("Arrêt du bot en cours...")
        try:
            await close_pool()
        except Exception as e:
            logger.error(f"Erreur lors de la fermeture de la BDD : {e}")
        await super().close()


bot = CosmandBot()


@bot.event
async def on_ready():
    logger.info(f"🚀 Connecté avec succès en tant que {bot.user} (ID: {bot.user.id})")


@bot.command(name="sync")
@commands.is_owner()
async def sync_commands(ctx: commands.Context, scope: str = None):
    """
    Commande de synchronisation des Slash Commands réservée au propriétaire.
    Usage :
      +sync        -> Synchronisation instantanée sur le serveur actuel (recommandé en dev)
      +sync global -> Synchronisation globale sur tous les serveurs
    """
    msg = await ctx.send("⏳ Synchronisation des commandes en cours...")
    try:
        if scope == "global":
            synced = await bot.tree.sync()
            await msg.edit(content=f"🌍 **{len(synced)}** commande(s) globale(s) synchronisée(s).")
        else:
            bot.tree.copy_global_to(guild=ctx.guild)
            synced = await bot.tree.sync(guild=ctx.guild)
            await msg.edit(content=f"🏠 **{len(synced)}** commande(s) synchronisée(s) pour **{ctx.guild.name}**.")
    except Exception as e:
        logger.exception(f"Échec de synchronisation des commandes : {e}")
        await msg.edit(content=f"❌ Erreur lors de la synchronisation : {e}")


async def main():
    token = os.getenv("DISCORD_TOKEN")
    if not token or token == "votre_token_ici":
        logger.critical(
            "Le token Discord (DISCORD_TOKEN) est manquant ou non configuré dans le fichier .env !"
        )
        sys.exit(1)

    async with bot:
        await bot.start(token)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Interruption par l'utilisateur reçue. Fin du programme.")