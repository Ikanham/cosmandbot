import random
import math
import logging
from datetime import datetime, timezone
import discord
from discord import app_commands
from discord.ext import commands, tasks
from db import fetchone, fetchall, execute
from utils.permissions import can_manage, get_guild_timezone, DEFAULT_TZ

logger = logging.getLogger("Countdowns")


def format_remaining(delta):
    total_seconds = delta.total_seconds()
    if total_seconds <= 0:
        return None

    ceil_days = max(1, math.ceil(total_seconds / 86400.0))
    years, rem_days = divmod(ceil_days, 365)
    months, days = divmod(rem_days, 30)

    parts = []
    if years > 0:
        parts.append(f"{years} an{'s' if years > 1 else ''}")
    if months > 0:
        parts.append(f"{months} mois")
    if days > 0 or (years == 0 and months == 0):
        parts.append(f"{days} jour{'s' if days > 1 else ''}")

    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return " et ".join(parts)
    return ", ".join(parts[:-1]) + " et " + parts[-1]


def build_message(title: str, remaining_str: str, event_date: datetime | None = None) -> str:
    """Construit un message festif avec timestamp natif Discord interactif."""
    if event_date:
        ts = int(event_date.replace(tzinfo=timezone.utc).timestamp())
        templates = [
            f"🎉 **{title}** : <t:{ts}:F> (<t:{ts}:R> — encore {remaining_str}) !",
            f"⏳ Plus que {remaining_str} avant **{title}** (<t:{ts}:R>) !",
            f"🚀 **{title}** approche à grands pas : plus que {remaining_str} (<t:{ts}:R>) !",
            f"🔥 Compte à rebours : dans {remaining_str}, c'est **{title}** (<t:{ts}:D>) !",
            f"⭐ Préparez-vous : dans {remaining_str} (<t:{ts}:R>), c’est **{title}** !",
        ]
    else:
        templates = [
            f"🎉 Il reste {remaining_str} avant **{title}** !",
            f"⏳ Plus que {remaining_str} avant **{title}** !",
            f"🚀 {remaining_str} restants avant **{title}** !",
            f"🔥 Le compte à rebours continue : {remaining_str} avant **{title}** !",
            f"⭐ Préparez-vous : dans {remaining_str}, c’est **{title}** !",
        ]
    return random.choice(templates)


async def countdown_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    """Autocomplétion intelligente des comptes à rebours pour suppression rapide."""
    if not interaction.guild_id:
        return []
    try:
        rows = await fetchall(
            "SELECT id, title FROM countdowns WHERE guild_id=%s ORDER BY id DESC LIMIT 25",
            (interaction.guild_id,),
        )
    except Exception:
        return []

    choices = []
    current_lower = current.lower().strip()
    for r in rows:
        label = f"#{r['id']} - {r['title']}"[:100]
        if not current_lower or current_lower in label.lower():
            choices.append(app_commands.Choice(name=label, value=str(r["id"])))
    return choices[:25]


class Countdowns(commands.Cog, name="Countdowns"):
    def __init__(self, bot):
        self.bot = bot
        self._sent_today: set[tuple[int, str]] = set()
        self.daily_task.start()

    def cog_unload(self):
        self.daily_task.cancel()

    rebours_group = app_commands.Group(
        name="rebours",
        description="Gestion des comptes à rebours",
        default_permissions=discord.Permissions(manage_guild=True),
    )

    @rebours_group.command(
        name="ajouter", description="Ajouter un compte à rebours."
    )
    @can_manage()
    @app_commands.describe(
        date="Format YYYY-MM-DD",
        heure="Format HH:MM",
        titre="Nom de l'événement",
    )
    async def add_countdown(
        self,
        interaction: discord.Interaction,
        date: str,
        heure: str,
        titre: str,
    ):
        tz = await get_guild_timezone(interaction.guild_id)

        try:
            local_dt = datetime.strptime(
                f"{date.strip()} {heure.strip()}", "%Y-%m-%d %H:%M"
            ).replace(tzinfo=tz)
            utc_dt = local_dt.astimezone(timezone.utc).replace(tzinfo=None)
        except Exception:
            await interaction.response.send_message(
                "❌ Format invalide. Utilise `YYYY-MM-DD` et `HH:MM`.",
                ephemeral=True,
            )
            return

        now_utc = discord.utils.utcnow().replace(tzinfo=None)
        if utc_dt <= now_utc:
            await interaction.response.send_message(
                "⚠️ Impossible d’ajouter un compte à rebours déjà passé.",
                ephemeral=True,
            )
            return

        await execute(
            "INSERT INTO countdowns(guild_id, title, event_date, created_by) VALUES (%s, %s, %s, %s)",
            (interaction.guild_id, titre.strip(), utc_dt, interaction.user.id),
        )

        ts = int(local_dt.timestamp())
        await interaction.response.send_message(
            f"✅ Compte à rebours ajouté : **{titre.strip()}** fixé au <t:{ts}:F> (<t:{ts}:R>)"
        )

    @rebours_group.command(
        name="liste", description="Lister tous les comptes à rebours du serveur."
    )
    @can_manage()
    async def list_countdowns(self, interaction: discord.Interaction):
        rows = await fetchall(
            "SELECT id, title, event_date FROM countdowns WHERE guild_id=%s",
            (interaction.guild_id,),
        )
        if not rows:
            await interaction.response.send_message(
                "Aucun compte à rebours.", ephemeral=True
            )
            return

        now = discord.utils.utcnow().replace(tzinfo=None)
        rendered = []
        for r in rows:
            remaining = r["event_date"] - now
            remaining_str = format_remaining(remaining)
            if not remaining_str:
                await execute(
                    "DELETE FROM countdowns WHERE id=%s", (r["id"],)
                )
                continue
            rendered.append(
                (
                    remaining.total_seconds(),
                    f"`#{r['id']}` " + build_message(r["title"], remaining_str, r["event_date"]),
                )
            )

        if not rendered:
            await interaction.response.send_message(
                "Aucun compte à rebours à venir.", ephemeral=True
            )
            return

        rendered.sort(key=lambda x: x[0])
        messages = [m for _, m in rendered]

        chunks = []
        current_chunk = []
        current_len = 0
        header = "⏳ **Comptes à rebours actifs :**\n"

        for m in messages:
            if current_len + len(m) + 1 > 1800:
                chunks.append("\n".join(current_chunk))
                current_chunk = [m]
                current_len = len(m)
            else:
                current_chunk.append(m)
                current_len += len(m) + 1

        if current_chunk:
            chunks.append("\n".join(current_chunk))

        await interaction.response.send_message(header + chunks[0])
        for extra in chunks[1:]:
            await interaction.followup.send(extra)

    @rebours_group.command(
        name="supprimer",
        description="Supprimer un compte à rebours par nom ou ID.",
    )
    @can_manage()
    @app_commands.describe(nom_ou_id="Sélectionne ou tape le compte à rebours à supprimer")
    @app_commands.autocomplete(nom_ou_id=countdown_autocomplete)
    async def remove_countdown(
        self, interaction: discord.Interaction, nom_ou_id: str
    ):
        guild_id = interaction.guild_id
        target = nom_ou_id.strip()

        if target.isdigit():
            cid = int(target)
            row = await fetchone(
                "SELECT title FROM countdowns WHERE id=%s AND guild_id=%s",
                (cid, guild_id),
            )
            if row:
                await execute(
                    "DELETE FROM countdowns WHERE id=%s AND guild_id=%s",
                    (cid, guild_id),
                )
                await interaction.response.send_message(
                    f"🗑️ Compte à rebours `#{cid}` (**{row['title']}**) supprimé."
                )
                return

        exact = await fetchall(
            "SELECT id, title FROM countdowns WHERE guild_id=%s AND LOWER(title)=LOWER(%s)",
            (guild_id, target),
        )
        if exact:
            ids = [r["id"] for r in exact]
            placeholders = ",".join(["%s"] * len(ids))
            await execute(
                f"DELETE FROM countdowns WHERE id IN ({placeholders})", ids
            )
            await interaction.response.send_message(
                f"🗑️ Compte(s) à rebours supprimé(s) : {', '.join(r['title'] for r in exact)}"
            )
            return

        await interaction.response.send_message(
            f"⚠️ Aucun compte à rebours trouvé pour **{nom_ou_id}**.",
            ephemeral=True,
        )

    @tasks.loop(minutes=1.0)
    async def daily_task(self):
        try:
            settings = await fetchall("SELECT * FROM guild_settings", ())
        except Exception as e:
            logger.error(f"Erreur de lecture BDD dans daily_task : {e}")
            return

        for row in settings:
            guild_id = int(row["guild_id"])
            guild = self.bot.get_guild(guild_id)
            if not guild or not row.get("countdown_channel_id"):
                continue

            tz = await get_guild_timezone(guild_id)
            tz_now = datetime.now(tz)

            hour_cfg = (
                row["countdown_hour"]
                if row.get("countdown_hour") is not None
                else 8
            )
            minute_cfg = (
                row["countdown_minute"]
                if row.get("countdown_minute") is not None
                else 0
            )

            current_key_time = tz_now.strftime("%Y-%m-%d %H:%M")
            key = (guild_id, current_key_time)

            today_prefix = tz_now.strftime("%Y-%m-%d")
            self._sent_today = {k for k in self._sent_today if k[1].startswith(today_prefix)}

            if tz_now.hour == hour_cfg and tz_now.minute == minute_cfg and key not in self._sent_today:
                crows = await fetchall(
                    "SELECT id, title, event_date FROM countdowns WHERE guild_id=%s",
                    (row["guild_id"],),
                )
                if not crows:
                    continue

                now_utc = discord.utils.utcnow().replace(tzinfo=None)
                rendered = []
                for c in crows:
                    remaining = c["event_date"] - now_utc
                    remaining_str = format_remaining(remaining)
                    if not remaining_str:
                        await execute(
                            "DELETE FROM countdowns WHERE id=%s", (c["id"],)
                        )
                        continue
                    rendered.append(
                        (
                            remaining.total_seconds(),
                            build_message(c["title"], remaining_str, c["event_date"]),
                        )
                    )

                if rendered:
                    rendered.sort(key=lambda x: x[0])
                    channel = guild.get_channel(int(row["countdown_channel_id"]))
                    if channel:
                        try:
                            msg_content = "\n".join(m for _, m in rendered)
                            await channel.send(
                                msg_content[:2000],
                                allowed_mentions=discord.AllowedMentions.none(),
                            )
                            self._sent_today.add(key)
                        except Exception as e:
                            logger.warning(f"Erreur d'envoi du compte à rebours #{channel.name}: {e}")

    @daily_task.before_loop
    async def before_daily_task(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(Countdowns(bot))