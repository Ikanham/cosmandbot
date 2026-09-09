import logging
import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger("Errors")


class ErrorHandler(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        bot.tree.error(self.on_app_command_error)

    async def _send_error(self, interaction: discord.Interaction, message: str):
        """Envoie le message d'erreur via followup ou response selon l'état de l'interaction."""
        try:
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
        except discord.HTTPException:
            pass

    async def on_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ):
        # Gestion des permissions refusées
        if isinstance(
            error,
            (
                app_commands.MissingRole,
                app_commands.MissingPermissions,
                app_commands.CheckFailure,
            ),
        ):
            await self._send_error(
                interaction, "❌ Tu n'as pas la permission d'exécuter cette commande."
            )
            return

        # Gestion des cooldowns
        if isinstance(error, app_commands.CommandOnCooldown):
            await self._send_error(
                interaction,
                f"⏳ Commande en pause. Réessaie dans **{error.retry_after:.1f}** seconde(s).",
            )
            return

        cmd_name = interaction.command.name if interaction.command else "Inconnue"
        guild_name = interaction.guild.name if interaction.guild else "DM"
        logger.exception(
            f"Exception lors de la commande /{cmd_name} (Serveur: {guild_name}, Utilisateur: {interaction.user}): {error}"
        )

        await self._send_error(
            interaction, "⚠️ Une erreur inattendue est survenue lors de l'exécution de la commande."
        )

    @commands.Cog.listener()
    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError):
        """Gestion des erreurs pour les commandes préfixées (ex: +sync)."""
        if isinstance(error, (commands.NotOwner, commands.MissingPermissions)):
            await ctx.send("❌ Vous n'avez pas la permission d'exécuter cette commande.")
            return
        if isinstance(error, commands.CommandNotFound):
            return

        logger.exception(f"Erreur sur la commande préfixée '{ctx.command}': {error}")
        await ctx.send("⚠️ Une erreur est survenue lors de l'exécution de la commande.")


async def setup(bot):
    await bot.add_cog(ErrorHandler(bot))