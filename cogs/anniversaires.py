import logging
from datetime import datetime
import discord
from discord import app_commands
from discord.ext import commands, tasks
from db import fetchall, fetchone, execute
from utils.date_parser import parse_date_str
from utils.permissions import get_guild_timezone, can_manage

logger = logging.getLogger("Anniversaires")


class Anniversaires(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Clés sous la forme : (guild_id, 'YYYY-MM-DD')
        self._sent_today: set[tuple[int, str]] = set()
        self.birthday_check.start()

    def cog_unload(self):
        self.birthday_check.cancel()

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        try:
            await execute(
                "DELETE FROM birthdays WHERE guild_id=%s AND member_id=%s AND is_custom=0",
                (member.guild.id, member.id),
            )
        except Exception as e:
            logger.error(f"Erreur lors de la suppression de l'anniversaire du membre {member.id}: {e}")

    anniv_group = app_commands.Group(
        name="anniversaire", description="Gestion des anniversaires"
    )

    @anniv_group.command(
        name="liste", description="Affiche la liste complète des anniversaires."
    )
    async def list_anniv(self, interaction: discord.Interaction):
        rows = await fetchall(
            "SELECT member_id, display_name, date, is_custom FROM birthdays WHERE guild_id=%s",
            (interaction.guild_id,),
        )
        if not rows:
            await interaction.response.send_message(
                "Aucun anniversaire enregistré.", ephemeral=True
            )
            return

        today = datetime.now()
        prochains = []
        for r in rows:
            member = (
                interaction.guild.get_member(r["member_id"])
                if not r["is_custom"] and r["member_id"] != 0
                else None
            )
            display_name = member.display_name if member else r["display_name"]

            try:
                day, month = map(int, r["date"].split("/"))
            except ValueError:
                continue

            # Gestion sécurisée du 29 février sur années non bissextiles
            try:
                date_anniv = datetime(today.year, month, day)
            except ValueError:
                date_anniv = datetime(today.year, 3, 1)

            if date_anniv.date() < today.date():
                try:
                    date_anniv = datetime(today.year + 1, month, day)
                except ValueError:
                    date_anniv = datetime(today.year + 1, 3, 1)

            prochains.append((date_anniv, display_name, r["date"]))

        prochains.sort(key=lambda x: x[0])
        display_list = [f"• **{p[1]}** : {p[2]}" for p in prochains]

        chunks = []
        current_chunk = []
        current_len = 0
        header = "🎂 **Anniversaires enregistrés :**\n"

        for item in display_list:
            if current_len + len(item) + 1 > 1800:
                chunks.append("\n".join(current_chunk))
                current_chunk = [item]
                current_len = len(item)
            else:
                current_chunk.append(item)
                current_len += len(item) + 1

        if current_chunk:
            chunks.append("\n".join(current_chunk))

        await interaction.response.send_message(header + chunks[0])
        for extra in chunks[1:]:
            await interaction.followup.send(extra)

    @anniv_group.command(
        name="definir", description="Enregistre ou modifie un anniversaire."
    )
    @app_commands.describe(
        date="Format JJ/MM ou 1er février",
        membre="Membre (Admin seulement pour un tiers)",
    )
    async def set_anniv(
        self,
        interaction: discord.Interaction,
        date: str,
        membre: discord.Member = None,
    ):
        target = membre or interaction.user
        is_self = target.id == interaction.user.id
        is_admin = interaction.user.guild_permissions.manage_guild

        if not is_self and not is_admin:
            await interaction.response.send_message(
                "⚠️ Tu ne peux modifier que ton propre anniversaire.",
                ephemeral=True,
            )
            return

        date_formatee = parse_date_str(date)
        if not date_formatee:
            await interaction.response.send_message(
                "⚠️ Format invalide. Utilise `JJ/MM` ou `1er février`.",
                ephemeral=True,
            )
            return

        row = await fetchone(
            "SELECT id FROM birthdays WHERE guild_id=%s AND member_id=%s AND is_custom=0",
            (interaction.guild_id, target.id),
        )
        if row:
            await execute(
                "UPDATE birthdays SET date=%s, display_name=%s WHERE id=%s",
                (date_formatee, target.display_name, row["id"]),
            )
            await interaction.response.send_message(
                f"🔄 Anniversaire de **{target.display_name}** mis à jour pour le **{date_formatee}** !"
            )
        else:
            await execute(
                "INSERT INTO birthdays (guild_id, member_id, display_name, date, is_custom) VALUES (%s, %s, %s, %s, 0)",
                (
                    interaction.guild_id,
                    target.id,
                    target.display_name,
                    date_formatee,
                ),
            )
            await interaction.response.send_message(
                f"✅ Anniversaire de **{target.display_name}** enregistré pour le **{date_formatee}** !"
            )

    @anniv_group.command(
        name="supprimer", description="Supprime un anniversaire (Admin/Mod)."
    )
    @can_manage()
    async def del_anniv(
        self, interaction: discord.Interaction, membre: discord.Member
    ):
        await execute(
            "DELETE FROM birthdays WHERE guild_id=%s AND member_id=%s",
            (interaction.guild_id, membre.id),
        )
        await interaction.response.send_message(
            f"✅ Anniversaire de **{membre.display_name}** supprimé.",
            ephemeral=True,
        )

    @tasks.loop(minutes=1)
    async def birthday_check(self):
        try:
            settings_rows = await fetchall("SELECT * FROM guild_settings", ())
        except Exception as e:
            logger.error(f"Erreur de lecture guild_settings dans birthday_check : {e}")
            return

        for settings in settings_rows:
            guild_id = settings["guild_id"]
            tz = await get_guild_timezone(guild_id)
            now = datetime.now(tz)

            today_str = f"{now.day:02d}/{now.month:02d}"
            today_iso = now.strftime("%Y-%m-%d")
            key = (guild_id, today_iso)

            self._sent_today = {k for k in self._sent_today if k[1] == today_iso}

            birthday_hour = (
                settings.get("birthday_hour")
                if settings.get("birthday_hour") is not None
                else 8
            )

            if now.hour == birthday_hour and key not in self._sent_today:
                guild = self.bot.get_guild(guild_id)
                if not guild:
                    continue

                birthday_channel_id = settings.get("birthday_channel")
                channel = (
                    guild.get_channel(birthday_channel_id)
                    if birthday_channel_id
                    else guild.system_channel
                )

                if channel:
                    try:
                        birthdays_today = await fetchall(
                            "SELECT member_id, display_name, is_custom FROM birthdays WHERE guild_id=%s AND date=%s",
                            (guild_id, today_str),
                        )
                        if birthdays_today:
                            mentions = [
                                f"<@{r['member_id']}>" if not r["is_custom"] else f"**{r['display_name']}**"
                                for r in birthdays_today
                            ]
                            if len(mentions) == 1:
                                msg = f"Coucou tout le monde ! 🎉\nAujourd’hui, c’est l’anniversaire de {mentions[0]} 🥳🎂"
                            else:
                                group_str = ", ".join(mentions[:-1]) + f" et {mentions[-1]}"
                                msg = f"Coucou tout le monde ! 🎉\nAujourd’hui, nous célébrons les anniversaires de {group_str} 🥳🎂"

                            await channel.send(
                                msg,
                                allowed_mentions=discord.AllowedMentions(
                                    users=True, roles=False, everyone=False
                                ),
                            )
                        self._sent_today.add(key)
                    except Exception as e:
                        logger.exception(f"Erreur lors du traitement des anniversaires pour guild {guild_id}: {e}")

    @birthday_check.before_loop
    async def before_birthday_check(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(Anniversaires(bot))