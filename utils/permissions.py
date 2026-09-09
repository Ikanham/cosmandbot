import os
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones
import discord
from discord import app_commands
from db import get_guild_settings

DEFAULT_ROLE_MOD_ID = int(os.getenv("DEFAULT_ROLE_MOD_ID", 1533849622340964417))
DEFAULT_TZ = os.getenv("DEFAULT_TZ", "Europe/Paris")


def is_valid_timezone(tz_name: str) -> bool:
    """Vérifie si le fuseau horaire est un fuseau IANA valide."""
    return tz_name in available_timezones()


async def get_guild_timezone(guild_id: int | None) -> ZoneInfo:
    """Retourne l'objet ZoneInfo configuré pour le serveur avec repli sécurisé."""
    if not guild_id:
        return ZoneInfo(DEFAULT_TZ)

    settings = await get_guild_settings(guild_id)
    tz_str = settings.get("timezone") or DEFAULT_TZ
    try:
        return ZoneInfo(tz_str)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo(DEFAULT_TZ)


async def can_manage_check(interaction: discord.Interaction) -> bool:
    """
    Vérifie si l'utilisateur est autorisé à exécuter des actions d'administration / modération.
    Autorise :
    1. Le propriétaire du serveur
    2. Les membres ayant la permission 'Gérer le serveur' (manage_guild)
    3. Les membres possédant le rôle modérateur configuré ou par défaut
    """
    if not interaction.guild or not interaction.user:
        return False

    # 1. Propriétaire du serveur
    if interaction.user.id == interaction.guild.owner_id:
        return True

    # 2. Permission native de gestion
    if hasattr(interaction.user, "guild_permissions") and interaction.user.guild_permissions.manage_guild:
        return True

    # 3. Rôle modérateur configuré ou par défaut
    if isinstance(interaction.user, discord.Member):
        settings = await get_guild_settings(interaction.guild.id)
        mod_role_id = settings.get("mod_role_id") or DEFAULT_ROLE_MOD_ID
        return any(role.id == mod_role_id for role in interaction.user.roles)

    return False


def can_manage():
    """Décorateur d'autorisation pour les commandes d'administration."""
    async def predicate(interaction: discord.Interaction) -> bool:
        return await can_manage_check(interaction)
    return app_commands.check(predicate)


async def build_settings_embed(guild: discord.Guild) -> discord.Embed:
    """Génère l'embed unifié et complet des paramètres du serveur."""
    settings = await get_guild_settings(guild.id)

    welcome_ch = (
        f"<#{settings['welcome_channel_id']}>"
        if settings.get("welcome_channel_id")
        else "*Non configuré*"
    )
    anniv_ch = (
        f"<#{settings['birthday_channel']}>"
        if settings.get("birthday_channel")
        else "*Non configuré*"
    )
    countdown_ch = (
        f"<#{settings['countdown_channel_id']}>"
        if settings.get("countdown_channel_id")
        else "*Non configuré*"
    )
    log_ch = (
        f"<#{settings['log_channel_id']}>"
        if settings.get("log_channel_id")
        else "*Non configuré*"
    )
    goodday_ch = (
        f"<#{settings['goodday_channel']}>"
        if settings.get("goodday_channel")
        else "*Non configuré*"
    )
    mod_role = (
        f"<@&{settings['mod_role_id']}>"
        if settings.get("mod_role_id")
        else "*Rôle par défaut*"
    )

    anniv_hour = settings.get("birthday_hour", 8)
    countdown_hour = settings.get("countdown_hour", 8)
    countdown_minute = settings.get("countdown_minute", 0)
    goodday_hour = settings.get("goodday_hour", 8)

    tz = await get_guild_timezone(guild.id)

    embed = discord.Embed(
        title=f"⚙️ Paramètres du serveur : {guild.name}",
        color=discord.Color.blurple(),
    )
    embed.add_field(
        name="👋 Arrivées & Départs", value=f"- Salon : {welcome_ch}", inline=False
    )
    embed.add_field(
        name="🎂 Anniversaires",
        value=f"- Salon : {anniv_ch}\n- Heure : **{anniv_hour:02d}:00**",
        inline=False,
    )
    embed.add_field(
        name="📅 Comptes à rebours",
        value=f"- Salon : {countdown_ch}\n- Heure : **{countdown_hour:02d}:{countdown_minute:02d}**",
        inline=False,
    )
    embed.add_field(
        name="🌞 Bonne journée",
        value=f"- Salon : {goodday_ch}\n- Heure : **{goodday_hour:02d}:00**",
        inline=False,
    )
    embed.add_field(
        name="📋 Logs Modération", value=f"- Salon : {log_ch}", inline=False
    )
    embed.add_field(
        name="🛡️ Rôle Modérateur", value=f"- Rôle : {mod_role}", inline=False
    )
    embed.add_field(
        name="🌍 Fuseau horaire", value=f"- Fuseau : **{tz.key}**", inline=False
    )
    return embed
