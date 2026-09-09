import discord
from discord import app_commands
from discord.ext import commands
from utils.permissions import can_manage, build_settings_embed


class Settings(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(
        name="settings",
        description="Affiche tous les paramètres configurés pour le serveur.",
    )
    @app_commands.default_permissions(manage_guild=True)
    @can_manage()
    async def settings(self, interaction: discord.Interaction):
        embed = await build_settings_embed(interaction.guild)
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Settings(bot))