import json
import logging
import discord
from discord import app_commands
from discord.ext import commands
from db import fetchone, fetchall, execute
from utils.permissions import can_manage

logger = logging.getLogger("Conventions")

DEFAULT_CONVENTION_CHANNEL_ID = 1533849624366940219


def build_convention_embed(convention: dict, participants: list[dict], role: discord.Role | None) -> discord.Embed:
    """Construit l'Embed de la convention avec le texte d'annonce Markdown et les listes par jour."""
    title = convention["title"]
    location = convention["location"]
    description = convention.get("description") or ""
    days_list = json.loads(convention["days_json"])

    embed = discord.Embed(
        title=f"🎭 {title}",
        color=discord.Color.from_rgb(203, 166, 247),
        timestamp=discord.utils.utcnow(),
    )

    embed.description = "ℹ️ *Cliquez sur les boutons ci-dessous pour indiquer vos jours de présence et recevoir le rôle associé !*"
    embed.add_field(name="📍 Lieu", value=f"**{location}**", inline=False)

    # Répartition des participants par jour
    for day in days_list:
        day_parts = [p for p in participants if p["day_name"] == day]
        count = len(day_parts)
        if day_parts:
            members_list = "\n".join(f"• <@{p['user_id']}>" for p in day_parts)
        else:
            members_list = "*(Aucun participant pour le moment)*"

        embed.add_field(
            name=f"📅 {day} ({count})",
            value=members_list[:1024],
            inline=True,
        )

    # Membres en cours de réflexion
    maybes = [p for p in participants if p["day_name"] == "__maybe__"]
    if maybes:
        maybes_list = "\n".join(f"• <@{p['user_id']}>" for p in maybes)
        embed.add_field(
            name=f"💭 En réflexion ({len(maybes)})",
            value=maybes_list[:1024],
            inline=True,
        )

    # Membres ayant indiqué ne pas venir
    absents = [p for p in participants if p["day_name"] == "__absent__"]
    if absents:
        embed.add_field(
            name="❌ Ne viennent pas",
            value=f"**{len(absents)}** membre(s)",
            inline=True,
        )

    # Décompte unique des participants ayant le rôle (exclut absents et réflexion)
    active_user_ids = {p["user_id"] for p in participants if p["day_name"] not in ("__absent__", "__maybe__")}

    embed.add_field(
        name="👥 Total participants confirmés",
        value=f"**{len(active_user_ids)}** membre(s)",
        inline=False,
    )
    embed.set_footer(text="CosmandBot • Organisation Cosplay")
    return embed


async def update_convention_embed(guild: discord.Guild, conv_id: int):
    """Met à jour l'Embed de la convention en direct après chaque interaction."""
    conv = await fetchone("SELECT * FROM conventions WHERE id=%s", (conv_id,))
    if not conv:
        return

    channel = guild.get_channel(int(conv["channel_id"]))
    if not channel:
        return

    try:
        message = await channel.fetch_message(int(conv["message_id"]))
    except (discord.NotFound, discord.Forbidden):
        return

    participants = await fetchall(
        "SELECT user_id, day_name FROM convention_participants WHERE convention_id=%s ORDER BY id ASC",
        (conv_id,),
    )
    role = guild.get_role(int(conv["role_id"]))

    days_list = json.loads(conv["days_json"])
    view = ConventionView(conv_id, days_list)
    embed = build_convention_embed(conv, participants, role)
    content = conv.get("description") or None

    try:
        await message.edit(content=content, embed=embed, view=view)
    except discord.HTTPException as e:
        logger.error(f"Erreur lors de la mise à jour de l'embed convention #{conv_id} : {e}")


class DayButton(discord.ui.Button):
    def __init__(self, conv_id: int, day_name: str):
        super().__init__(
            style=discord.ButtonStyle.success,
            label=day_name[:80],
            custom_id=f"conv:{conv_id}:day:{day_name}",
        )
        self.conv_id = conv_id
        self.day_name = day_name

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        user = interaction.user

        conv = await fetchone("SELECT * FROM conventions WHERE id=%s", (self.conv_id,))
        if not conv:
            await interaction.followup.send("❌ Cette convention n'existe plus.", ephemeral=True)
            return

        role = guild.get_role(int(conv["role_id"]))

        # Vérifier si l'utilisateur est déjà inscrit pour ce jour (Toggle)
        existing = await fetchone(
            "SELECT id FROM convention_participants WHERE convention_id=%s AND user_id=%s AND day_name=%s",
            (self.conv_id, user.id, self.day_name),
        )

        if existing:
            # Désinscription de ce jour
            await execute(
                "DELETE FROM convention_participants WHERE convention_id=%s AND user_id=%s AND day_name=%s",
                (self.conv_id, user.id, self.day_name),
            )

            # Vérifier s'il reste d'autres jours pour cet utilisateur
            remaining = await fetchall(
                "SELECT id FROM convention_participants WHERE convention_id=%s AND user_id=%s AND day_name NOT IN ('__absent__', '__maybe__')",
                (self.conv_id, user.id),
            )

            if not remaining and role:
                try:
                    await user.remove_roles(role, reason="Désinscription totale de la convention")
                except discord.HTTPException:
                    pass
                msg = f"❌ Tu t'es désinscrit(e) pour le **{self.day_name}**.\nN'ayant plus aucun jour sélectionné, le rôle {role.mention} t'a été retiré."
            else:
                role_str = role.mention if role else "de la convention"
                msg = f"❌ Tu t'es désinscrit(e) pour le **{self.day_name}** (tu conserves le rôle {role_str} pour tes autres jours)."
        else:
            # Inscription à ce jour (retire les statuts 'absent' ou 'maybe' si présents)
            await execute(
                "DELETE FROM convention_participants WHERE convention_id=%s AND user_id=%s AND day_name IN ('__absent__', '__maybe__')",
                (self.conv_id, user.id),
            )
            await execute(
                "INSERT INTO convention_participants (convention_id, user_id, day_name) VALUES (%s, %s, %s)",
                (self.conv_id, user.id, self.day_name),
            )

            if role:
                try:
                    await user.add_roles(role, reason="Inscription à la convention")
                except discord.HTTPException:
                    pass

            role_str = role.mention if role else "de la convention"
            msg = f"✅ Tu es inscrit(e) pour le **{self.day_name}** ! Le rôle {role_str} t'a été attribué."

        # Mise à jour de l'Embed en direct
        await update_convention_embed(guild, self.conv_id)
        await interaction.followup.send(msg, ephemeral=True)


class MaybeButton(discord.ui.Button):
    def __init__(self, conv_id: int):
        super().__init__(
            style=discord.ButtonStyle.secondary,
            label="Je réfléchis",
            emoji="💭",
            custom_id=f"conv:{conv_id}:maybe",
        )
        self.conv_id = conv_id

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        user = interaction.user

        conv = await fetchone("SELECT * FROM conventions WHERE id=%s", (self.conv_id,))
        if not conv:
            await interaction.followup.send("❌ Cette convention n'existe plus.", ephemeral=True)
            return

        role = guild.get_role(int(conv["role_id"]))

        # Effacer tous les jours et statuts précédents
        await execute(
            "DELETE FROM convention_participants WHERE convention_id=%s AND user_id=%s",
            (self.conv_id, user.id),
        )
        # Enregistrer en tant qu'indécis
        await execute(
            "INSERT INTO convention_participants (convention_id, user_id, day_name) VALUES (%s, %s, '__maybe__')",
            (self.conv_id, user.id),
        )

        if role:
            try:
                await user.remove_roles(role, reason="Indication de réflexion pour la convention")
            except discord.HTTPException:
                pass

        role_str = role.mention if role else "de la convention"
        msg = f"💭 Tu as indiqué être en réflexion pour cette convention.\nTes choix de présence ont été réinitialisés et le rôle {role_str} t'a été retiré en attendant ta décision !"

        await update_convention_embed(guild, self.conv_id)
        await interaction.followup.send(msg, ephemeral=True)


class AbsentButton(discord.ui.Button):
    def __init__(self, conv_id: int):
        super().__init__(
            style=discord.ButtonStyle.danger,
            label="Ne vient pas",
            emoji="❌",
            custom_id=f"conv:{conv_id}:absent",
        )
        self.conv_id = conv_id

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        user = interaction.user

        conv = await fetchone("SELECT * FROM conventions WHERE id=%s", (self.conv_id,))
        if not conv:
            await interaction.followup.send("❌ Cette convention n'existe plus.", ephemeral=True)
            return

        role = guild.get_role(int(conv["role_id"]))

        # Effacer tous les jours de présence
        await execute(
            "DELETE FROM convention_participants WHERE convention_id=%s AND user_id=%s",
            (self.conv_id, user.id),
        )
        # Enregistrer en tant qu'absent
        await execute(
            "INSERT INTO convention_participants (convention_id, user_id, day_name) VALUES (%s, %s, '__absent__')",
            (self.conv_id, user.id),
        )

        if role:
            try:
                await user.remove_roles(role, reason="Indication d'absence à la convention")
            except discord.HTTPException:
                pass

        role_str = role.mention if role else "de la convention"
        msg = f"❌ Tu as indiqué ne pas venir. Tes choix ont été réinitialisés et le rôle {role_str} t'a été retiré."

        await update_convention_embed(guild, self.conv_id)
        await interaction.followup.send(msg, ephemeral=True)


class ConventionView(discord.ui.View):
    """Vue persistante contenant les boutons dynamiques des jours, le bouton réflexion et le bouton absent."""
    def __init__(self, conv_id: int, days_list: list[str]):
        super().__init__(timeout=None)
        self.conv_id = conv_id

        for day in days_list:
            self.add_item(DayButton(conv_id, day))
        self.add_item(MaybeButton(conv_id))
        self.add_item(AbsentButton(conv_id))


class ConventionModal(discord.ui.Modal, title="Nouvelle Convention Cosplay"):
    titre = discord.ui.TextInput(
        label="Nom de la convention",
        placeholder="Ex: Japan Expo Paris 2026",
        required=True,
        max_length=100,
    )
    role_name = discord.ui.TextInput(
        label="Nom du rôle Discord",
        placeholder="Ex: Japan Expo 2026",
        required=True,
        max_length=100,
    )
    lieu = discord.ui.TextInput(
        label="Lieu / Emplacement",
        placeholder="Ex: Parc des Expositions Villepinte",
        required=True,
        max_length=100,
    )
    jours = discord.ui.TextInput(
        label="Jours disponibles (séparés par virgules)",
        placeholder="Ex: Jeudi, Vendredi, Samedi, Dimanche",
        required=True,
        max_length=150,
    )
    annonce = discord.ui.TextInput(
        label="Texte d'annonce (Markdown accepté)",
        style=discord.TextStyle.paragraph,
        placeholder="Ex: **Préparez vos cosplays !**\nIndiquez vos jours de présence pour organiser nos sorties ensemble.",
        required=False,
        max_length=1500,
    )

    def __init__(self, bot, target_channel: discord.TextChannel):
        super().__init__()
        self.bot = bot
        self.target_channel = target_channel

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild

        # Découpage et nettoyage des jours saisis
        raw_days = [j.strip() for j in self.jours.value.split(",") if j.strip()]
        if not raw_days:
            await interaction.followup.send(
                "❌ Vous devez indiquer au moins un jour valide (séparés par des virgules).",
                ephemeral=True,
            )
            return

        if len(raw_days) > 15:
            await interaction.followup.send(
                "❌ Limite de 15 jours par événement dépassée.", ephemeral=True
            )
            return

        # Création automatique du rôle Discord
        role_nom = self.role_name.value.strip()
        try:
            role = await guild.create_role(
                name=role_nom,
                color=discord.Color.from_rgb(203, 166, 247),
                mentionable=True,
                reason=f"Rôle automatique créé pour la convention {self.titre.value.strip()} par {interaction.user.display_name}",
            )
        except discord.Forbidden:
            await interaction.followup.send(
                "❌ Le bot n'a pas la permission de créer des rôles (`manage_roles`).",
                ephemeral=True,
            )
            return
        except discord.HTTPException as e:
            await interaction.followup.send(
                f"❌ Erreur lors de la création du rôle : {e}",
                ephemeral=True,
            )
            return

        days_json = json.dumps(raw_days, ensure_ascii=False)

        # Enregistrement en base de données
        conv_id = await execute(
            """
            INSERT INTO conventions (guild_id, channel_id, message_id, role_id, title, role_name, location, description, days_json)
            VALUES (%s, %s, 0, %s, %s, %s, %s, %s, %s)
            """,
            (
                guild.id,
                self.target_channel.id,
                role.id,
                self.titre.value.strip(),
                role_nom,
                self.lieu.value.strip(),
                self.annonce.value.strip() if self.annonce.value else "",
                days_json,
            ),
        )

        conv_data = {
            "id": conv_id,
            "title": self.titre.value.strip(),
            "location": self.lieu.value.strip(),
            "description": self.annonce.value.strip() if self.annonce.value else "",
            "role_id": role.id,
            "days_json": days_json,
        }

        # Création de l'Embed et de la Vue interactive
        embed = build_convention_embed(conv_data, [], role)
        view = ConventionView(conv_id, raw_days)
        annonce_text = self.annonce.value.strip() if (self.annonce.value and self.annonce.value.strip()) else None

        allowed = discord.AllowedMentions(
            everyone=interaction.user.guild_permissions.mention_everyone,
            roles=True,
            users=True,
        )

        try:
            msg = await self.target_channel.send(
                content=annonce_text,
                embed=embed,
                view=view,
                allowed_mentions=allowed,
            )
        except (discord.Forbidden, discord.HTTPException) as e:
            await execute("DELETE FROM conventions WHERE id=%s", (conv_id,))
            try:
                await role.delete(reason="Annulation création convention")
            except discord.HTTPException:
                pass
            await interaction.followup.send(
                f"❌ Impossible d'envoyer le message dans {self.target_channel.mention} : {e}",
                ephemeral=True,
            )
            return

        # Mise à jour de l'ID du message en BDD et persistance dans le bot
        await execute("UPDATE conventions SET message_id=%s WHERE id=%s", (msg.id, conv_id))
        self.bot.add_view(view, message_id=msg.id)

        await interaction.followup.send(
            f"✅ Convention **{self.titre.value.strip()}** créée et publiée avec succès dans {self.target_channel.mention} !\n"
            f"🎟️ Rôle associé : {role.mention}",
            ephemeral=True,
        )


async def convention_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[int]]:
    """Autocomplétion des conventions actives pour l'archivage."""
    if not interaction.guild_id:
        return []
    try:
        rows = await fetchall(
            "SELECT id, title, location FROM conventions WHERE guild_id=%s ORDER BY id DESC LIMIT 25",
            (interaction.guild_id,),
        )
    except Exception:
        return []

    choices = []
    current_lower = current.lower().strip()
    for r in rows:
        label = f"#{r['id']} - {r['title']} ({r['location']})"[:100]
        if not current_lower or current_lower in label.lower() or current_lower in str(r["id"]):
            choices.append(app_commands.Choice(name=label, value=r["id"]))
    return choices[:25]


class ConventionsCog(commands.Cog, name="Conventions"):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        """Réenregistre toutes les vues persistantes des conventions lors du démarrage."""
        try:
            rows = await fetchall("SELECT id, days_json, message_id FROM conventions", ())
            for r in rows:
                if r.get("message_id") and r.get("days_json"):
                    days = json.loads(r["days_json"])
                    view = ConventionView(r["id"], days)
                    self.bot.add_view(view, message_id=int(r["message_id"]))
            logger.info(f"✅ {len(rows)} vue(s) persistante(s) de convention réenregistrée(s).")
        except Exception as e:
            logger.warning(f"Impossible de réenregistrer les vues de convention : {e}")

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        """Nettoie les présences des membres quittant le serveur."""
        try:
            await execute(
                "DELETE FROM convention_participants WHERE user_id=%s",
                (member.id,),
            )
        except Exception as e:
            logger.error(f"Erreur lors du nettoyage des conventions pour le membre {member.id} : {e}")

    convention_group = app_commands.Group(
        name="convention",
        description="Organisation des conventions et événements cosplay",
        default_permissions=discord.Permissions(manage_guild=True),
    )

    @convention_group.command(
        name="creer",
        description="Créer une nouvelle convention avec sélection de jours et rôle automatique.",
    )
    @can_manage()
    @app_commands.describe(
        salon="Salon d'affichage (optionnel, par défaut salon officiel des sorties)"
    )
    async def creer_convention(
        self,
        interaction: discord.Interaction,
        salon: discord.TextChannel = None,
    ):
        target_channel = (
            salon
            or interaction.guild.get_channel(DEFAULT_CONVENTION_CHANNEL_ID)
            or interaction.channel
        )
        await interaction.response.send_modal(
            ConventionModal(self.bot, target_channel)
        )

    @convention_group.command(
        name="archiver",
        description="Clôturer et supprimer une convention ainsi que son rôle associé.",
    )
    @can_manage()
    @app_commands.describe(convention_id="Sélectionnez la convention à archiver")
    @app_commands.autocomplete(convention_id=convention_autocomplete)
    async def archiver_convention(
        self, interaction: discord.Interaction, convention_id: int
    ):
        await interaction.response.defer(ephemeral=True)

        conv = await fetchone(
            "SELECT * FROM conventions WHERE id=%s AND guild_id=%s",
            (convention_id, interaction.guild_id),
        )
        if not conv:
            await interaction.followup.send(
                "❌ Convention introuvable.", ephemeral=True
            )
            return

        # Supprimer le rôle associé
        role = interaction.guild.get_role(int(conv["role_id"]))
        if role:
            try:
                await role.delete(reason=f"Archivage de la convention #{conv['id']}")
            except discord.HTTPException:
                pass

        # Supprimer le message d'annonce si possible
        channel = interaction.guild.get_channel(int(conv["channel_id"]))
        if channel:
            try:
                msg = await channel.fetch_message(int(conv["message_id"]))
                await msg.delete()
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass

        # Supprimer de la BDD
        await execute("DELETE FROM convention_participants WHERE convention_id=%s", (convention_id,))
        await execute("DELETE FROM conventions WHERE id=%s", (convention_id,))

        await interaction.followup.send(
            f"🗑️ La convention **{conv['title']}** a été archivée avec succès.",
            ephemeral=True,
        )

    @convention_group.command(
        name="liste",
        description="Lister toutes les conventions actives sur le serveur.",
    )
    @can_manage()
    async def lister_conventions(self, interaction: discord.Interaction):
        rows = await fetchall(
            "SELECT id, title, location, channel_id, role_id FROM conventions WHERE guild_id=%s ORDER BY id DESC",
            (interaction.guild_id,),
        )
        if not rows:
            await interaction.response.send_message(
                "ℹ️ Aucune convention enregistrée sur ce serveur.", ephemeral=True
            )
            return

        lines = []
        for r in rows:
            lines.append(
                f"• `#{r['id']}` **{r['title']}** (Lieu: {r['location']}) — Salon: <#{r['channel_id']}> — Rôle: <@&{r['role_id']}>"
            )

        embed = discord.Embed(
            title="🎭 Conventions Cosplay Actives",
            description="\n".join(lines),
            color=discord.Color.from_rgb(180, 190, 254),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(ConventionsCog(bot))
