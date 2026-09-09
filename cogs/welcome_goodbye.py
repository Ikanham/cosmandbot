from datetime import timedelta
import logging
import discord
from discord.ext import commands
from db import get_guild_settings

logger = logging.getLogger("WelcomeGoodbye")


class WelcomeGoodbyeCog(commands.Cog, name="WelcomeGoodbye"):
    def __init__(self, bot):
        self.bot = bot

    async def _get_welcome_channel(self, guild: discord.Guild) -> discord.TextChannel | None:
        if not guild:
            return None
        settings = await get_guild_settings(guild.id)
        channel_id = settings.get("welcome_channel_id")
        if not channel_id:
            return None
        return guild.get_channel(int(channel_id))

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot:
            return

        guild = member.guild
        channel = await self._get_welcome_channel(guild)
        if not channel:
            return

        human_count = sum(1 for m in guild.members if not m.bot) if guild.members else (guild.member_count or 1)

        embed = discord.Embed(
            title="👋 Bienvenue !",
            description=(
                f"Bienvenue à **{member.display_name}** sur le serveur **{guild.name}** !\n"
                f"Nous sommes désormais **{human_count}** membres."
            ),
            color=discord.Color.green(),
        )
        if member.display_avatar:
            embed.set_thumbnail(url=member.display_avatar.url)

        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            pass

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        if member.bot:
            return

        guild = member.guild
        now = discord.utils.utcnow()
        time_window = timedelta(seconds=10)

        # 1. Vérification des Bannissements
        if guild.me.guild_permissions.ban_members:
            try:
                ban_entry = await guild.fetch_ban(member)
                if ban_entry:
                    return
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass

        # 2. Vérification des Expulsions (Kick) via Audit Logs
        if guild.me.guild_permissions.view_audit_log:
            try:
                async for entry in guild.audit_logs(
                    limit=5, action=discord.AuditLogAction.kick
                ):
                    if entry.target and entry.target.id == member.id:
                        if now - entry.created_at <= time_window:
                            return
            except (discord.Forbidden, discord.HTTPException):
                pass

        # 3. Envoi du message dans le salon d'accueil / départ
        channel = await self._get_welcome_channel(guild)
        if not channel:
            return

        human_count = sum(1 for m in guild.members if not m.bot) if guild.members else max(0, (guild.member_count or 1) - 1)

        embed = discord.Embed(
            title="👋 Au revoir !",
            description=(
                f"**{member.display_name}** a quitté le serveur.\n"
                f"Nous sommes désormais **{human_count}** membres."
            ),
            color=discord.Color.red(),
        )
        if member.display_avatar:
            embed.set_thumbnail(url=member.display_avatar.url)

        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            pass


async def setup(bot):
    await bot.add_cog(WelcomeGoodbyeCog(bot))