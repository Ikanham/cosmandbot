import random
import logging
from datetime import datetime, timezone
import discord
from discord import app_commands
from discord.ext import commands, tasks
from db import fetchall, fetchone, execute, invalidate_guild_cache
from utils.permissions import can_manage, get_guild_timezone

logger = logging.getLogger("Scheduler")


async def scheduled_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[int]]:
    """Autocomplétion des messages planifiés en attente."""
    if not interaction.guild_id:
        return []
    try:
        rows = await fetchall(
            "SELECT id, run_at, content FROM scheduled_messages WHERE guild_id=%s AND sent=0 ORDER BY run_at ASC LIMIT 25",
            (interaction.guild_id,),
        )
    except Exception:
        return []

    tz = await get_guild_timezone(interaction.guild_id)
    choices = []
    current_lower = current.lower().strip()

    for r in rows:
        date_str = (
            r["run_at"]
            .replace(tzinfo=timezone.utc)
            .astimezone(tz)
            .strftime("%d/%m %H:%M")
        )
        preview = r["content"].split("\n")[0][:35]
        label = f"#{r['id']} ({date_str}) - {preview}"[:100]
        if not current_lower or current_lower in label.lower() or current_lower in str(r["id"]):
            choices.append(app_commands.Choice(name=label, value=r["id"]))

    return choices[:25]


async def goodday_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[int]]:
    """Autocomplétion des messages de bonne journée disponibles."""
    if not interaction.guild_id:
        return []
    try:
        rows = await fetchall(
            "SELECT id, content FROM daily_messages WHERE guild_id=%s ORDER BY id ASC LIMIT 25",
            (interaction.guild_id,),
        )
    except Exception:
        return []

    choices = []
    current_lower = current.lower().strip()

    for r in rows:
        preview = r["content"].split("\n")[0][:60]
        label = f"#{r['id']} - {preview}"[:100]
        if not current_lower or current_lower in label.lower() or current_lower in str(r["id"]):
            choices.append(app_commands.Choice(name=label, value=r["id"]))

    return choices[:25]


class ScheduleModal(discord.ui.Modal, title="Planifier un message"):
    content_input = discord.ui.TextInput(
        label="Contenu du message",
        style=discord.TextStyle.paragraph,
        placeholder="Écris ton message planifié ici...",
        required=True,
        max_length=2000,
    )

    def __init__(
        self,
        channel: discord.TextChannel,
        date_str: str,
        time_str: str,
        tz,
    ):
        super().__init__()
        self.channel = channel
        self.date_str = date_str
        self.time_str = time_str
        self.tz = tz

    async def on_submit(self, interaction: discord.Interaction):
        content = self.content_input.value.strip()

        try:
            local_dt = datetime.strptime(
                f"{self.date_str} {self.time_str}", "%Y-%m-%d %H:%M"
            ).replace(tzinfo=self.tz)
            run_at_utc = local_dt.astimezone(timezone.utc).replace(tzinfo=None)
        except Exception:
            await interaction.response.send_message(
                "❌ Date ou heure invalide. Format requis : `YYYY-MM-DD` et `HH:MM`",
                ephemeral=True,
            )
            return

        now_utc = discord.utils.utcnow().replace(tzinfo=None)
        if run_at_utc <= now_utc:
            await interaction.response.send_message(
                "⚠️ Impossible de planifier un message dans le passé.",
                ephemeral=True,
            )
            return

        await execute(
            "INSERT INTO scheduled_messages(guild_id, channel_id, author_id, content, run_at) VALUES (%s, %s, %s, %s, %s)",
            (
                interaction.guild_id,
                self.channel.id,
                interaction.user.id,
                content,
                run_at_utc,
            ),
        )

        ts = int(local_dt.timestamp())
        await interaction.response.send_message(
            f"✅ Message planifié pour <t:{ts}:F> (<t:{ts}:R>) dans {self.channel.mention}.",
            ephemeral=True,
        )


class EditGoodDayModal(
    discord.ui.Modal, title="Modifier un message de bonne journée"
):
    content_input = discord.ui.TextInput(
        label="Nouveau message de bonne journée",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=2000,
    )

    def __init__(self, message_id: int, current_content: str):
        super().__init__()
        self.message_id = message_id
        self.content_input.default = current_content

    async def on_submit(self, interaction: discord.Interaction):
        new_content = self.content_input.value.strip()

        await execute(
            "UPDATE daily_messages SET content=%s WHERE id=%s AND guild_id=%s",
            (new_content, self.message_id, interaction.guild_id),
        )

        await interaction.response.send_message(
            f"✅ Le message de bonne journée `#{self.message_id}` a été mis à jour :\n`{new_content}`",
            ephemeral=True,
        )


class Scheduler(commands.Cog, name="Scheduler"):
    def __init__(self, bot):
        self.bot = bot
        self._goodday_sent: set[tuple[int, str]] = set()
        self.tick.start()
        self.goodday_task.start()

    def cog_unload(self):
        self.tick.cancel()
        self.goodday_task.cancel()

    planifier_group = app_commands.Group(
        name="planifier",
        description="Planification d'envoi de messages",
        default_permissions=discord.Permissions(manage_guild=True),
    )
    bonnejournee_group = app_commands.Group(
        name="bonnejournee",
        description="Gestion des messages quotidiens de bonne journée",
        default_permissions=discord.Permissions(manage_guild=True),
    )

    # --- Groupe /planifier ---

    @planifier_group.command(
        name="message",
        description="Ouvre un formulaire pour planifier un message unique.",
    )
    @can_manage()
    @app_commands.describe(
        channel="Salon d'envoi",
        date="Format YYYY-MM-DD",
        heure="Format HH:MM",
    )
    async def schedule_message(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        date: str,
        heure: str,
    ):
        tz = await get_guild_timezone(interaction.guild_id)
        await interaction.response.send_modal(
            ScheduleModal(channel, date.strip(), heure.strip(), tz)
        )

    @planifier_group.command(
        name="liste", description="Lister tous les messages planifiés."
    )
    @can_manage()
    async def list_scheduled(self, interaction: discord.Interaction):
        rows = await fetchall(
            "SELECT id, channel_id, content, run_at, sent FROM scheduled_messages WHERE guild_id=%s ORDER BY run_at ASC",
            (interaction.guild_id,),
        )
        if not rows:
            await interaction.response.send_message(
                "Aucun message planifié.", ephemeral=True
            )
            return

        tz = await get_guild_timezone(interaction.guild_id)
        lines = []
        for r in rows:
            utc_dt = r["run_at"].replace(tzinfo=timezone.utc)
            ts = int(utc_dt.timestamp())
            status = "✅ envoyé" if r["sent"] == 1 else ("❌ échec" if r["sent"] == -1 else "🕒 à venir")
            preview = r["content"].split("\n")[0][:45]
            lines.append(
                f"`#{r['id']}` <#{r['channel_id']}> — <t:{ts}:F> (<t:{ts}:R>) — {status}\n> {preview}"
            )

        chunks = []
        current_chunk = []
        current_len = 0
        header = "⏰ **Messages planifiés :**\n\n"

        for line in lines:
            if current_len + len(line) + 2 > 1800:
                chunks.append("\n\n".join(current_chunk))
                current_chunk = [line]
                current_len = len(line)
            else:
                current_chunk.append(line)
                current_len += len(line) + 2

        if current_chunk:
            chunks.append("\n\n".join(current_chunk))

        await interaction.response.send_message(header + chunks[0], ephemeral=True)
        for extra in chunks[1:]:
            await interaction.followup.send(extra, ephemeral=True)

    @planifier_group.command(
        name="supprimer",
        description="Supprimer un message planifié par son identifiant.",
    )
    @can_manage()
    @app_commands.describe(message_id="Sélectionne le message planifié à supprimer")
    @app_commands.autocomplete(message_id=scheduled_autocomplete)
    async def remove_scheduled(
        self, interaction: discord.Interaction, message_id: int
    ):
        await execute(
            "DELETE FROM scheduled_messages WHERE id=%s AND guild_id=%s AND sent=0",
            (message_id, interaction.guild_id),
        )
        await interaction.response.send_message(
            f"🗑️ Message planifié `#{message_id}` supprimé.", ephemeral=True
        )

    # --- Groupe /bonnejournee ---

    @bonnejournee_group.command(
        name="ajouter",
        description="Ajouter un message de bonne journée aléatoire.",
    )
    @can_manage()
    async def add_goodday(self, interaction: discord.Interaction, message: str):
        await execute(
            "INSERT INTO daily_messages(guild_id, content) VALUES (%s, %s)",
            (interaction.guild_id, message.strip()),
        )
        await interaction.response.send_message(
            f"✅ Message de bonne journée ajouté : `{message.strip()}`"
        )

    @bonnejournee_group.command(
        name="modifier",
        description="Modifier le texte d'un message de bonne journée via son ID.",
    )
    @can_manage()
    @app_commands.describe(
        message_id="Sélectionne le message de bonne journée à modifier"
    )
    @app_commands.autocomplete(message_id=goodday_autocomplete)
    async def edit_goodday(
        self, interaction: discord.Interaction, message_id: int
    ):
        row = await fetchone(
            "SELECT content FROM daily_messages WHERE id=%s AND guild_id=%s",
            (message_id, interaction.guild_id),
        )
        if not row:
            await interaction.response.send_message(
                f"❌ Aucun message de bonne journée trouvé avec l'ID `#{message_id}`.",
                ephemeral=True,
            )
            return

        await interaction.response.send_modal(
            EditGoodDayModal(
                message_id=message_id, current_content=row["content"]
            )
        )

    @bonnejournee_group.command(
        name="supprimer",
        description="Supprimer une phrase de bonne journée par ID.",
    )
    @can_manage()
    @app_commands.describe(
        message_id="Sélectionne le message de bonne journée à supprimer"
    )
    @app_commands.autocomplete(message_id=goodday_autocomplete)
    async def del_goodday(
        self, interaction: discord.Interaction, message_id: int
    ):
        await execute(
            "DELETE FROM daily_messages WHERE id=%s AND guild_id=%s",
            (message_id, interaction.guild_id),
        )
        await interaction.response.send_message(
            f"🗑️ Message de bonne journée `#{message_id}` supprimé.",
            ephemeral=True,
        )

    @bonnejournee_group.command(
        name="liste",
        description="Voir la liste des messages de bonne journée enregistrés.",
    )
    @can_manage()
    async def list_goodday(self, interaction: discord.Interaction):
        rows = await fetchall(
            "SELECT id, content FROM daily_messages WHERE guild_id=%s ORDER BY id ASC",
            (interaction.guild_id,),
        )
        if not rows:
            await interaction.response.send_message(
                "⚠️ Aucun message de bonne journée enregistré.", ephemeral=True
            )
            return

        lines = [f"`#{r['id']}` {r['content']}" for r in rows]
        chunks = []
        current_chunk = []
        current_len = 0
        header = "🌞 **Messages de bonne journée disponibles :**\n"

        for line in lines:
            if current_len + len(line) + 1 > 1800:
                chunks.append("\n".join(current_chunk))
                current_chunk = [line]
                current_len = len(line)
            else:
                current_chunk.append(line)
                current_len += len(line) + 1

        if current_chunk:
            chunks.append("\n".join(current_chunk))

        await interaction.response.send_message(header + chunks[0], ephemeral=True)
        for extra in chunks[1:]:
            await interaction.followup.send(extra, ephemeral=True)

    @bonnejournee_group.command(
        name="salon",
        description="Définir le salon des messages de bonne journée.",
    )
    @can_manage()
    async def set_goodday_channel(
        self, interaction: discord.Interaction, channel: discord.TextChannel
    ):
        await execute(
            "INSERT INTO guild_settings (guild_id, goodday_channel) VALUES (%s, %s) ON DUPLICATE KEY UPDATE goodday_channel=%s",
            (interaction.guild_id, channel.id, channel.id),
        )
        invalidate_guild_cache(interaction.guild_id)
        await interaction.response.send_message(
            f"✅ Les messages de bonne journée seront envoyés dans {channel.mention}"
        )

    @bonnejournee_group.command(
        name="heure",
        description="Définir l'heure quotidienne d'envoi (0–23h).",
    )
    @can_manage()
    async def set_goodday_hour(
        self, interaction: discord.Interaction, heure: int
    ):
        if not (0 <= heure <= 23):
            await interaction.response.send_message(
                "⚠️ L'heure doit être comprise entre 0 et 23.", ephemeral=True
            )
            return
        await execute(
            "INSERT INTO guild_settings (guild_id, goodday_hour) VALUES (%s, %s) ON DUPLICATE KEY UPDATE goodday_hour=%s",
            (interaction.guild_id, heure, heure),
        )
        invalidate_guild_cache(interaction.guild_id)
        await interaction.response.send_message(
            f"✅ Messages de bonne journée programmés à **{heure:02d}:00**."
        )

    # --- Tâches asynchrones de fond ---

    @tasks.loop(seconds=30.0)
    async def tick(self):
        try:
            due = await fetchall(
                "SELECT id, guild_id, channel_id, content, run_at FROM scheduled_messages WHERE sent=0 AND run_at <= UTC_TIMESTAMP() ORDER BY run_at ASC LIMIT 25"
            )
        except Exception as e:
            logger.error(f"Erreur SQL dans scheduler.tick : {e}")
            return

        for r in due:
            msg_id = r["id"]
            guild = self.bot.get_guild(int(r["guild_id"]))
            if not guild:
                await execute("UPDATE scheduled_messages SET sent=-1 WHERE id=%s", (msg_id,))
                continue

            channel = guild.get_channel(int(r["channel_id"]))
            if not channel:
                await execute("UPDATE scheduled_messages SET sent=-1 WHERE id=%s", (msg_id,))
                continue

            try:
                await channel.send(
                    r["content"],
                    allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
                )
                await execute("DELETE FROM scheduled_messages WHERE id=%s", (msg_id,))
            except discord.Forbidden:
                logger.warning(f"Permissions insuffisantes pour envoyer le message planifié #{msg_id} dans #{channel.name}.")
                await execute("UPDATE scheduled_messages SET sent=-1 WHERE id=%s", (msg_id,))
            except Exception as e:
                logger.error(f"Erreur d'envoi du message planifié #{msg_id} : {e}")
                await execute("UPDATE scheduled_messages SET sent=-1 WHERE id=%s", (msg_id,))

    @tasks.loop(minutes=1.0)
    async def goodday_task(self):
        try:
            rows = await fetchall(
                "SELECT guild_id, goodday_channel, goodday_hour, timezone FROM guild_settings",
                (),
            )
        except Exception as e:
            logger.error(f"Erreur SQL dans goodday_task : {e}")
            return

        for s in rows:
            ghour = s.get("goodday_hour")
            if ghour is None:
                continue

            guild_id = int(s["guild_id"])
            tz = await get_guild_timezone(guild_id)
            now_local = datetime.now(tz)
            date_key = now_local.strftime("%Y-%m-%d")
            key = (guild_id, date_key)

            self._goodday_sent = {k for k in self._goodday_sent if k[1] == date_key}

            if now_local.hour == ghour and key not in self._goodday_sent:
                guild = self.bot.get_guild(guild_id)
                if not guild:
                    continue

                channel = (
                    guild.get_channel(int(s["goodday_channel"]))
                    if s.get("goodday_channel")
                    else guild.system_channel
                )
                if not channel:
                    continue

                choices = await fetchall(
                    "SELECT content FROM daily_messages WHERE guild_id=%s",
                    (guild.id,),
                )
                msg = (
                    random.choice(choices)["content"]
                    if choices
                    else "Bonne journée à tous !"
                )

                try:
                    await channel.send(
                        f"{msg}",
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
                    self._goodday_sent.add(key)
                except Exception as e:
                    logger.warning(f"Impossible d'envoyer la bonne journée dans #{channel.name} : {e}")

    @tick.before_loop
    async def before_tick(self):
        await self.bot.wait_until_ready()

    @goodday_task.before_loop
    async def before_goodday_task(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(Scheduler(bot))