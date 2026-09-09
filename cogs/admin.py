import logging
from datetime import timedelta
import discord
from discord import app_commands
from discord.ext import commands
from db import execute, get_guild_settings, invalidate_guild_cache
from utils.permissions import can_manage, is_valid_timezone, DEFAULT_TZ, build_settings_embed

logger = logging.getLogger("Admin")


class AdminCog(commands.Cog, name="Admin"):
    def __init__(self, bot):
        self.bot = bot

    config_group = app_commands.Group(
        name="config",
        description="Configuration globale du serveur",
        default_permissions=discord.Permissions(manage_guild=True),
    )
    purger_group = app_commands.Group(
        name="purger",
        description="Purge de messages dans un salon",
        default_permissions=discord.Permissions(manage_guild=True),
    )

    # --- Groupe /config ---

    @config_group.command(
        name="salon-accueil",
        description="Définir le salon pour l'annonce des arrivées et départs.",
    )
    @can_manage()
    async def set_welcome_channel(
        self, interaction: discord.Interaction, channel: discord.TextChannel
    ):
        await execute(
            """
            INSERT INTO guild_settings(guild_id, welcome_channel_id, timezone)
            VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE welcome_channel_id=VALUES(welcome_channel_id)
            """,
            (interaction.guild_id, channel.id, DEFAULT_TZ),
        )
        invalidate_guild_cache(interaction.guild_id)
        await interaction.response.send_message(
            f"✅ Salon d'accueil et de départ défini sur {channel.mention}"
        )

    @config_group.command(
        name="salon-anniversaire",
        description="Définir le salon d'annonce des anniversaires.",
    )
    @can_manage()
    async def set_birthday_channel(
        self, interaction: discord.Interaction, channel: discord.TextChannel
    ):
        await execute(
            """
            INSERT INTO guild_settings(guild_id, birthday_channel, timezone)
            VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE birthday_channel=VALUES(birthday_channel)
            """,
            (interaction.guild_id, channel.id, DEFAULT_TZ),
        )
        invalidate_guild_cache(interaction.guild_id)
        await interaction.response.send_message(
            f"✅ Salon des anniversaires défini sur {channel.mention}"
        )

    @config_group.command(
        name="heure-anniversaire",
        description="Définir l'heure d'annonce des anniversaires (0-23h).",
    )
    @can_manage()
    async def set_birthday_hour(
        self, interaction: discord.Interaction, heure: int
    ):
        heure = max(0, min(23, heure))
        await execute(
            """
            INSERT INTO guild_settings(guild_id, birthday_hour, timezone)
            VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE birthday_hour=VALUES(birthday_hour)
            """,
            (interaction.guild_id, heure, DEFAULT_TZ),
        )
        invalidate_guild_cache(interaction.guild_id)
        await interaction.response.send_message(
            f"✅ Heure d'annonce des anniversaires : **{heure:02d}:00**"
        )

    @config_group.command(
        name="salon-rebours",
        description="Définir le salon des comptes à rebours.",
    )
    @can_manage()
    async def set_countdown_channel(
        self, interaction: discord.Interaction, channel: discord.TextChannel
    ):
        await execute(
            """
            INSERT INTO guild_settings(guild_id, countdown_channel_id, timezone)
            VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE countdown_channel_id=VALUES(countdown_channel_id)
            """,
            (interaction.guild_id, channel.id, DEFAULT_TZ),
        )
        invalidate_guild_cache(interaction.guild_id)
        await interaction.response.send_message(
            f"✅ Salon des comptes à rebours défini sur {channel.mention}"
        )

    @config_group.command(
        name="heure-rebours",
        description="Heure quotidienne d'annonce des comptes à rebours.",
    )
    @can_manage()
    @app_commands.describe(hour="Heure (0-23)", minute="Minute (0-59)")
    async def set_countdown_time(
        self, interaction: discord.Interaction, hour: int, minute: int = 0
    ):
        hour = max(0, min(23, hour))
        minute = max(0, min(59, minute))
        await execute(
            """
            INSERT INTO guild_settings(guild_id, countdown_hour, countdown_minute, timezone)
            VALUES (%s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE countdown_hour=VALUES(countdown_hour), countdown_minute=VALUES(countdown_minute)
            """,
            (interaction.guild_id, hour, minute, DEFAULT_TZ),
        )
        invalidate_guild_cache(interaction.guild_id)
        await interaction.response.send_message(
            f"✅ Heure quotidienne des comptes à rebours : **{hour:02d}:{minute:02d}**"
        )

    @config_group.command(
        name="salon-logs",
        description="Définir le salon de journalisation des logs de modération.",
    )
    @can_manage()
    async def set_log_channel(
        self, interaction: discord.Interaction, channel: discord.TextChannel
    ):
        await execute(
            """
            INSERT INTO guild_settings (guild_id, log_channel_id)
            VALUES (%s, %s)
            ON DUPLICATE KEY UPDATE log_channel_id=VALUES(log_channel_id)
            """,
            (interaction.guild_id, channel.id),
        )
        invalidate_guild_cache(interaction.guild_id)
        await interaction.response.send_message(
            f"✅ Salon de journalisation (logs) défini sur {channel.mention}"
        )

    @config_group.command(
        name="role-mod",
        description="Définir le rôle modérateur autorisé à administrer le bot.",
    )
    @can_manage()
    async def set_mod_role(
        self, interaction: discord.Interaction, role: discord.Role
    ):
        try:
            await execute(
                """
                INSERT INTO guild_settings(guild_id, mod_role_id)
                VALUES (%s, %s)
                ON DUPLICATE KEY UPDATE mod_role_id=VALUES(mod_role_id)
                """,
                (interaction.guild_id, role.id),
            )
        except Exception:
            # Fallback si la colonne n'existe pas encore
            await execute(
                "ALTER TABLE guild_settings ADD COLUMN mod_role_id BIGINT NULL"
            )
            await execute(
                """
                INSERT INTO guild_settings(guild_id, mod_role_id)
                VALUES (%s, %s)
                ON DUPLICATE KEY UPDATE mod_role_id=VALUES(mod_role_id)
                """,
                (interaction.guild_id, role.id),
            )

        invalidate_guild_cache(interaction.guild_id)
        await interaction.response.send_message(
            f"✅ Rôle modérateur configuré sur {role.mention}"
        )

    @config_group.command(
        name="fuseau",
        description="Définir le fuseau horaire du serveur (ex: Europe/Paris, America/Montreal).",
    )
    @can_manage()
    async def set_timezone(self, interaction: discord.Interaction, tz: str):
        tz_clean = tz.strip()
        if not is_valid_timezone(tz_clean):
            await interaction.response.send_message(
                f"❌ Le fuseau `{tz_clean}` n'est pas un fuseau IANA valide.\n"
                f"Exemples valides : `Europe/Paris`, `America/Montreal`, `UTC`, `America/New_York`.",
                ephemeral=True,
            )
            return

        await execute(
            """
            INSERT INTO guild_settings(guild_id, timezone)
            VALUES (%s, %s)
            ON DUPLICATE KEY UPDATE timezone=VALUES(timezone)
            """,
            (interaction.guild_id, tz_clean),
        )
        invalidate_guild_cache(interaction.guild_id)
        await interaction.response.send_message(
            f"✅ Fuseau horaire défini sur `{tz_clean}`"
        )

    @config_group.command(
        name="afficher",
        description="Afficher tous les réglages actuels du serveur.",
    )
    @can_manage()
    async def view_settings(self, interaction: discord.Interaction):
        embed = await build_settings_embed(interaction.guild)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # --- Groupe /purger ---

    @purger_group.command(
        name="nombre", description="Supprime les X derniers messages du salon."
    )
    @can_manage()
    @app_commands.describe(nombre="Nombre de messages à supprimer (ex: 20)")
    async def purger_nombre(
        self, interaction: discord.Interaction, nombre: int
    ):
        if nombre <= 0 or nombre > 100:
            await interaction.response.send_message(
                "❌ Veuillez indiquer un nombre entre 1 et 100.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)
        channel = interaction.channel

        if not channel.permissions_for(interaction.guild.me).manage_messages:
            await interaction.followup.send(
                "❌ Je n'ai pas la permission de gérer/supprimer des messages dans ce salon.",
                ephemeral=True,
            )
            return

        try:
            deleted = await channel.purge(
                limit=nombre,
                reason=f"Purge de {nombre} message(s) par {interaction.user.display_name}",
            )
            count = len(deleted)
            await interaction.followup.send(
                f"🧹 **{count}** message(s) ont été supprimé(s).",
                ephemeral=True,
            )
        except discord.Forbidden:
            await interaction.followup.send(
                "❌ Permissions insuffisantes pour supprimer les messages.",
                ephemeral=True,
            )
        except discord.HTTPException as e:
            await interaction.followup.send(
                f"⚠️ Une erreur est survenue lors de la suppression : {e}",
                ephemeral=True,
            )

    @purger_group.command(
        name="minutes",
        description="Supprime les messages envoyés sur les X dernières minutes.",
    )
    @can_manage()
    @app_commands.describe(
        minutes="Nombre de minutes à remonter en arrière (ex: 5)"
    )
    async def purger_minutes(
        self, interaction: discord.Interaction, minutes: int
    ):
        if minutes <= 0 or minutes > 1440:
            await interaction.response.send_message(
                "❌ Veuillez indiquer un nombre de minutes valide (entre 1 et 1440 minutes).",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)
        channel = interaction.channel

        if not channel.permissions_for(interaction.guild.me).manage_messages:
            await interaction.followup.send(
                "❌ Je n'ai pas la permission de gérer/supprimer des messages dans ce salon.",
                ephemeral=True,
            )
            return

        cutoff_time = discord.utils.utcnow() - timedelta(minutes=minutes)

        def is_after_cutoff(msg: discord.Message) -> bool:
            return msg.created_at >= cutoff_time

        try:
            deleted = await channel.purge(
                limit=500,
                check=is_after_cutoff,
                reason=f"Purge des {minutes} dernière(s) minute(s) par {interaction.user.display_name}",
            )
            count = len(deleted)
            await interaction.followup.send(
                f"🧹 **{count}** message(s) envoyé(s) sur les **{minutes}** dernière(s) minute(s) ont été supprimé(s).",
                ephemeral=True,
            )
        except discord.Forbidden:
            await interaction.followup.send(
                "❌ Permissions insuffisantes pour supprimer les messages.",
                ephemeral=True,
            )
        except discord.HTTPException as e:
            await interaction.followup.send(
                f"⚠️ Une erreur est survenue lors de la suppression : {e}",
                ephemeral=True,
            )

    # --- Commande Hack ---

    @app_commands.command(
        name="hack",
        description="Purge les messages récents (10 min) et expulse un utilisateur compromis.",
    )
    @app_commands.default_permissions(manage_guild=True)
    @can_manage()
    @app_commands.describe(
        utilisateur="L'utilisateur dont le compte a été piraté"
    )
    async def hack_command(
        self, interaction: discord.Interaction, utilisateur: discord.Member
    ):
        if utilisateur.id == interaction.guild.owner_id:
            await interaction.response.send_message(
                "❌ Impossible d'expulser le propriétaire du serveur.",
                ephemeral=True,
            )
            return

        if utilisateur.id == interaction.guild.me.id:
            await interaction.response.send_message(
                "❌ Le bot ne peut pas s'expulser lui-même.",
                ephemeral=True,
            )
            return

        if (
            interaction.user.id != interaction.guild.owner_id
            and utilisateur.top_role >= interaction.user.top_role
        ):
            await interaction.response.send_message(
                "❌ Tu ne peux pas exécuter cette commande sur un membre ayant un rôle équivalent ou supérieur au tien.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        guild = interaction.guild
        last_message_time = None

        # Recherche optimisée : inspecte les salons textuels accessibles
        candidate_channels = [
            ch
            for ch in guild.text_channels
            if ch.permissions_for(guild.me).read_message_history
            and ch.permissions_for(guild.me).manage_messages
        ]

        for channel in candidate_channels:
            try:
                async for message in channel.history(limit=50):
                    if message.author.id == utilisateur.id:
                        if (
                            last_message_time is None
                            or message.created_at > last_message_time
                        ):
                            last_message_time = message.created_at
                        break
            except (discord.Forbidden, discord.HTTPException):
                continue

        deleted_count = 0

        if last_message_time:
            time_threshold = last_message_time - timedelta(minutes=10)

            def is_target_and_in_window(msg: discord.Message) -> bool:
                return (
                    msg.author.id == utilisateur.id
                    and msg.created_at >= time_threshold
                )

            for channel in candidate_channels:
                try:
                    deleted = await channel.purge(
                        limit=100,
                        check=is_target_and_in_window,
                        after=time_threshold - timedelta(seconds=5),
                    )
                    deleted_count += len(deleted)
                except (discord.Forbidden, discord.HTTPException):
                    continue

        reason_msg = f"Compte piraté - Expulsé par {interaction.user.display_name}"
        try:
            await utilisateur.kick(reason=reason_msg)
            kick_status = f"✅ **{utilisateur.display_name}** a été expulsé avec succès pour le motif : *\"{reason_msg}\"*."
        except discord.Forbidden:
            kick_status = "⚠️ Impossible d'expulser l'utilisateur (permissions insuffisantes ou rôle du bot trop bas)."
        except discord.HTTPException as e:
            kick_status = f"⚠️ Erreur lors de l'expulsion : {e}"

        msg_status = (
            f"🧹 **{deleted_count}** message(s) supprimé(s) (fenêtre de 10 min à partir de son dernier message)."
            if last_message_time
            else "ℹ️ Aucun message récent trouvé pour cet utilisateur."
        )

        await interaction.followup.send(
            f"{kick_status}\n{msg_status}", ephemeral=True
        )


async def setup(bot):
    await bot.add_cog(AdminCog(bot))