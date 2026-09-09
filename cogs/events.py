import os
import logging
import discord
from discord import app_commands
from discord.ext import commands
from db import fetchone, fetchall, execute, get_guild_settings
from utils.permissions import can_manage

logger = logging.getLogger("Events")

DEFAULT_CATEGORY_ID = int(os.getenv("DEFAULT_CATEGORY_ID", 1533852396596363264))
DEFAULT_TARGET_CHANNEL_ID = int(os.getenv("DEFAULT_TARGET_CHANNEL_ID", 1533849625218514955))


async def update_event_embed(guild: discord.Guild, event: dict):
    channel = guild.get_channel(int(event["channel_id"]))
    if not channel:
        return

    participants = await fetchall(
        "SELECT user_id FROM event_participants WHERE event_id=%s ORDER BY id ASC",
        (event["id"],),
    )
    total_participants = len(participants)
    max_slots = event["max_slots"]
    places_restantes = max(0, max_slots - total_participants)

    members_list = (
        "\n".join([f"• <@{p['user_id']}>" for p in participants])
        if participants
        else "*(Aucun participant pour le moment)*"
    )
    status_str = f"**{total_participants}/{max_slots}** inscrits *(**{places_restantes}** place{'s' if places_restantes > 1 else ''} restante{'s' if places_restantes > 1 else ''})*"

    embed = discord.Embed(
        title=f"🎉 Sortie : {event['title']}",
        color=discord.Color.from_rgb(203, 166, 247),
    )
    embed.add_field(
        name="📅 Date & Heure", value=event["event_date"], inline=True
    )
    embed.add_field(name="📍 Lieu", value=event["location"], inline=True)
    embed.add_field(
        name="👥 Places disponibles", value=status_str, inline=False
    )
    embed.add_field(
        name="📜 Liste des participants", value=members_list, inline=False
    )

    role = guild.get_role(int(event["role_id"]))
    if role:
        embed.add_field(
            name="🎟️ Rôle associé", value=role.mention, inline=False
        )

    try:
        async for msg in channel.history(limit=25, oldest_first=True):
            if msg.author == guild.me and msg.embeds:
                await msg.edit(embed=embed)
                return
        await channel.send(embed=embed)
    except discord.HTTPException as e:
        logger.warning(f"Erreur lors de la mise à jour de l'embed de sortie dans #{channel.name} : {e}")


class EventModal(discord.ui.Modal, title="Créer une nouvelle sortie"):
    titre = discord.ui.TextInput(
        label="Nom de la sortie",
        placeholder="Ex: Session Karting",
        required=True,
        max_length=100,
    )
    date_str = discord.ui.TextInput(
        label="Date et heure",
        placeholder="Ex: Samedi 20 Septembre à 14h00",
        required=True,
        max_length=100,
    )
    lieu = discord.ui.TextInput(
        label="Lieu",
        placeholder="Ex: Circuit de l'Europe",
        required=True,
        max_length=100,
    )
    places = discord.ui.TextInput(
        label="Nombre de places disponibles",
        placeholder="Ex: 10",
        required=True,
        max_length=5,
    )

    async def on_submit(self, interaction: discord.Interaction):
        places_raw = self.places.value.strip()

        if not places_raw.isdigit() or int(places_raw) <= 0:
            await interaction.response.send_message(
                "❌ **Erreur de saisie** : Le nombre de places doit être un nombre entier supérieur à 0.",
                ephemeral=True,
            )
            return

        max_slots = int(places_raw)
        guild = interaction.guild

        role = await guild.create_role(
            name=f"Sortie - {self.titre.value.strip()}"[:100],
            color=discord.Color.from_rgb(203, 166, 247),
            mentionable=True,
            reason=f"Création de sortie par {interaction.user.display_name}",
        )

        settings = await get_guild_settings(guild.id)
        cat_id = settings.get("event_category_id") or DEFAULT_CATEGORY_ID
        target_ch_id = settings.get("event_target_channel_id") or DEFAULT_TARGET_CHANNEL_ID

        category = guild.get_channel(cat_id)
        target_channel = guild.get_channel(target_ch_id)
        target_position = target_channel.position if target_channel else None

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(
                read_messages=False
            ),
            role: discord.PermissionOverwrite(
                read_messages=True, send_messages=True
            ),
            guild.me: discord.PermissionOverwrite(
                read_messages=True, send_messages=True
            ),
        }

        channel = await guild.create_text_channel(
            name=f"┃ sortie {self.titre.value.strip().lower().replace(' ', '-')}"[
                :100
            ],
            category=(
                category if isinstance(category, discord.CategoryChannel) else None
            ),
            overwrites=overwrites,
            reason=f"Salon de sortie pour {self.titre.value.strip()}",
        )

        if target_position is not None:
            try:
                await channel.edit(position=target_position)
            except discord.HTTPException:
                pass

        event_id = await execute(
            """
            INSERT INTO events (guild_id, channel_id, role_id, title, event_date, location, max_slots)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                guild.id,
                channel.id,
                role.id,
                self.titre.value.strip(),
                self.date_str.value.strip(),
                self.lieu.value.strip(),
                max_slots,
            ),
        )

        event = {
            "id": event_id,
            "guild_id": guild.id,
            "channel_id": channel.id,
            "role_id": role.id,
            "title": self.titre.value.strip(),
            "event_date": self.date_str.value.strip(),
            "location": self.lieu.value.strip(),
            "max_slots": max_slots,
        }

        await update_event_embed(guild, event)

        preview_embed = discord.Embed(
            title="🔍 Aperçu de la sortie générée",
            description=f"Le salon {channel.mention} et le rôle {role.mention} ont été configurés avec succès.",
            color=discord.Color.from_rgb(180, 190, 254),
        )
        preview_embed.add_field(
            name="Nom", value=self.titre.value.strip(), inline=True
        )
        preview_embed.add_field(
            name="Date", value=self.date_str.value.strip(), inline=True
        )
        preview_embed.add_field(
            name="Lieu", value=self.lieu.value.strip(), inline=True
        )
        preview_embed.add_field(
            name="Places totales", value=str(max_slots), inline=True
        )

        await interaction.response.send_message(
            embed=preview_embed, ephemeral=True
        )


class EditEventModal(discord.ui.Modal, title="Modifier la sortie"):
    def __init__(self, event: dict):
        super().__init__()
        self.event = event

        self.titre = discord.ui.TextInput(
            label="Nom de la sortie",
            default=event["title"],
            required=True,
            max_length=100,
        )
        self.date_str = discord.ui.TextInput(
            label="Date et heure",
            default=event["event_date"],
            required=True,
            max_length=100,
        )
        self.lieu = discord.ui.TextInput(
            label="Lieu",
            default=event["location"],
            required=True,
            max_length=100,
        )
        self.places = discord.ui.TextInput(
            label="Nombre de places disponibles",
            default=str(event["max_slots"]),
            required=True,
            max_length=5,
        )

        self.add_item(self.titre)
        self.add_item(self.date_str)
        self.add_item(self.lieu)
        self.add_item(self.places)

    async def on_submit(self, interaction: discord.Interaction):
        places_raw = self.places.value.strip()

        if not places_raw.isdigit() or int(places_raw) <= 0:
            await interaction.response.send_message(
                "❌ **Erreur de saisie** : Le nombre de places doit être un nombre entier supérieur à 0.",
                ephemeral=True,
            )
            return

        max_slots = int(places_raw)
        guild = interaction.guild
        new_title = self.titre.value.strip()
        new_date = self.date_str.value.strip()
        new_lieu = self.lieu.value.strip()

        await execute(
            "UPDATE events SET title=%s, event_date=%s, location=%s, max_slots=%s WHERE id=%s",
            (new_title, new_date, new_lieu, max_slots, self.event["id"]),
        )

        role = guild.get_role(int(self.event["role_id"]))
        if role:
            try:
                await role.edit(name=f"Sortie - {new_title}"[:100])
            except discord.HTTPException:
                pass

        channel = guild.get_channel(int(self.event["channel_id"]))
        if channel:
            try:
                await channel.edit(
                    name=f"┃ sortie {new_title.lower().replace(' ', '-')}"[:100]
                )
            except discord.HTTPException:
                pass

        updated_event = {
            "id": self.event["id"],
            "guild_id": self.event["guild_id"],
            "channel_id": self.event["channel_id"],
            "role_id": self.event["role_id"],
            "title": new_title,
            "event_date": new_date,
            "location": new_lieu,
            "max_slots": max_slots,
        }

        await update_event_embed(guild, updated_event)

        await interaction.response.send_message(
            f"✅ La sortie **{new_title}** a été mise à jour avec succès !",
            ephemeral=True,
        )


class EventsCog(commands.Cog, name="Events"):
    def __init__(self, bot):
        self.bot = bot

    sortie_group = app_commands.Group(
        name="sortie",
        description="Gestion des sorties et événements",
        default_permissions=discord.Permissions(manage_guild=True),
    )

    @sortie_group.command(
        name="creer",
        description="Ouvre le formulaire de création d'une nouvelle sortie.",
    )
    @can_manage()
    async def nouvelle_sortie(self, interaction: discord.Interaction):
        await interaction.response.send_modal(EventModal())

    @sortie_group.command(
        name="modifier",
        description="Modifier les informations de la sortie actuelle.",
    )
    @can_manage()
    async def modifier_sortie(self, interaction: discord.Interaction):
        event = await fetchone(
            "SELECT * FROM events WHERE guild_id=%s AND channel_id=%s",
            (interaction.guild_id, interaction.channel_id),
        )
        if not event:
            await interaction.response.send_message(
                "❌ Cette commande doit être exécutée dans le salon d'une sortie active.",
                ephemeral=True,
            )
            return

        await interaction.response.send_modal(EditEventModal(event))

    @sortie_group.command(
        name="ajouter", description="Inscrire un membre à une sortie."
    )
    @can_manage()
    @app_commands.describe(
        utilisateur="Le membre à inscrire",
        salon="Salon de la sortie (optionnel si dans le salon)",
    )
    async def ajouter_sortie(
        self,
        interaction: discord.Interaction,
        utilisateur: discord.Member,
        salon: discord.TextChannel = None,
    ):
        await interaction.response.defer()
        target_channel = salon or interaction.channel

        event = await fetchone(
            "SELECT * FROM events WHERE guild_id=%s AND channel_id=%s",
            (interaction.guild_id, target_channel.id),
        )
        if not event:
            await interaction.followup.send(
                f"❌ Le salon {target_channel.mention} n'est pas associé à une sortie enregistrée.",
                ephemeral=True,
            )
            return

        existing = await fetchone(
            "SELECT id FROM event_participants WHERE event_id=%s AND user_id=%s",
            (event["id"], utilisateur.id),
        )
        if existing:
            await interaction.followup.send(
                f"⚠️ **{utilisateur.display_name}** est déjà inscrit à cette sortie.",
                ephemeral=True,
            )
            return

        count_row = await fetchone(
            "SELECT COUNT(*) as total FROM event_participants WHERE event_id=%s",
            (event["id"],),
        )
        current_count = count_row["total"] if count_row else 0

        if current_count >= event["max_slots"]:
            await interaction.followup.send(
                f"❌ La sortie **{event['title']}** est complète (0 place restante).",
                ephemeral=True,
            )
            return

        role = interaction.guild.get_role(int(event["role_id"]))
        if role:
            try:
                await utilisateur.add_roles(role)
            except discord.HTTPException:
                pass

        await execute(
            "INSERT INTO event_participants (event_id, user_id) VALUES (%s, %s)",
            (event["id"], utilisateur.id),
        )
        await update_event_embed(interaction.guild, event)
        await interaction.followup.send(
            f"✅ **{utilisateur.display_name}** a été ajouté à la sortie **{event['title']}**."
        )

    @sortie_group.command(
        name="retirer",
        description="Retirer un utilisateur de la sortie liée au salon actuel.",
    )
    @can_manage()
    @app_commands.describe(utilisateur="Le membre à retirer")
    async def retirer_sortie(
        self, interaction: discord.Interaction, utilisateur: discord.Member
    ):
        await interaction.response.defer()

        event = await fetchone(
            "SELECT * FROM events WHERE guild_id=%s AND channel_id=%s",
            (interaction.guild_id, interaction.channel_id),
        )
        if not event:
            await interaction.followup.send(
                "❌ Cette commande doit être exécutée dans le salon d'une sortie active.",
                ephemeral=True,
            )
            return

        existing = await fetchone(
            "SELECT id FROM event_participants WHERE event_id=%s AND user_id=%s",
            (event["id"], utilisateur.id),
        )
        if not existing:
            await interaction.followup.send(
                f"⚠️ **{utilisateur.display_name}** n'est pas inscrit à cette sortie.",
                ephemeral=True,
            )
            return

        role = interaction.guild.get_role(int(event["role_id"]))
        if role:
            try:
                await utilisateur.remove_roles(role)
            except discord.HTTPException:
                pass

        await execute(
            "DELETE FROM event_participants WHERE event_id=%s AND user_id=%s",
            (event["id"], utilisateur.id),
        )
        await update_event_embed(interaction.guild, event)
        await interaction.followup.send(
            f"🗑️ **{utilisateur.display_name}** a été retiré de la sortie."
        )

    @sortie_group.command(
        name="archiver",
        description="Supprimer le rôle associé et le salon actuel de la sortie.",
    )
    @can_manage()
    async def archiver_sortie(self, interaction: discord.Interaction):
        await interaction.response.defer()

        event = await fetchone(
            "SELECT * FROM events WHERE guild_id=%s AND channel_id=%s",
            (interaction.guild_id, interaction.channel_id),
        )
        if not event:
            await interaction.followup.send(
                "❌ Cette commande doit être exécutée dans le salon de la sortie à archiver.",
                ephemeral=True,
            )
            return

        role = interaction.guild.get_role(int(event["role_id"]))
        if role:
            try:
                await role.delete(reason="Archivage de la sortie")
            except discord.HTTPException:
                pass

        # Suppression explicite des participants pour éviter les orphelins
        await execute("DELETE FROM event_participants WHERE event_id=%s", (event["id"],))
        await execute("DELETE FROM events WHERE id=%s", (event["id"],))
        await interaction.channel.delete(reason="Archivage de la sortie")


async def setup(bot):
    await bot.add_cog(EventsCog(bot))