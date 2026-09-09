import io
import logging
import re
import discord
from discord import app_commands
from discord.ext import commands
from utils.permissions import can_manage

logger = logging.getLogger("Say")

MAX_FILE_SIZE = 25 * 1024 * 1024  # 25 Mo (limite standard Discord)


def resolve_emojis(guild: discord.Guild, text: str) -> str:
    """Remplace les codes :nom_emoji: par les vraies balises Discord d'émojis du serveur."""
    if not text or ":" not in text or not guild:
        return text

    emoji_map = {}
    for e in guild.emojis:
        emoji_map[e.name.lower()] = str(e)

    if hasattr(guild, "_state") and hasattr(guild._state, "emojis"):
        for e in guild._state.emojis:
            if e.name.lower() not in emoji_map:
                emoji_map[e.name.lower()] = str(e)

    pattern = r"(?<!<a)(?<!<):([a-zA-Z0-9_]+):"

    def repl(m):
        name = m.group(1).lower()
        return emoji_map.get(name, m.group(0))

    return re.sub(pattern, repl, text)


async def send_cloned_message(
    target_channel: discord.TextChannel,
    source_message: discord.Message,
    author: discord.Member,
    guild: discord.Guild,
) -> tuple[bool, str]:
    """Télécharge les pièces jointes du message source et renvoie le contenu dans le salon cible de manière sécurisée."""
    files = []
    for attachment in source_message.attachments:
        if attachment.size > MAX_FILE_SIZE:
            return (
                False,
                f"❌ Le fichier `{attachment.filename}` dépasse la limite autorisée de 25 Mo.",
            )
        try:
            data = await attachment.read()
            fp = io.BytesIO(data)
            fp.seek(0)
            files.append(discord.File(fp, filename=attachment.filename))
        except Exception as e:
            logger.error(f"Erreur de lecture de la pièce jointe {attachment.filename} : {e}")
            return False, f"❌ Impossible de télécharger `{attachment.filename}`."

    content = source_message.content or ""

    # Sécurité des mentions : seuls les utilisateurs ayant 'mention_everyone' peuvent pinger @everyone ou @here
    can_mention_everyone = (
        author.guild_permissions.mention_everyone
        if hasattr(author, "guild_permissions")
        else False
    )

    # Remplacement des mentions de rôles uniquement si autorisés
    if guild:
        for role in guild.roles:
            if f"@{role.name}" in content and role.name != "@everyone":
                if role.mentionable or can_mention_everyone or author.guild_permissions.administrator:
                    content = content.replace(f"@{role.name}", role.mention)

        # Résolution des émojis personnalisés du serveur
        content = resolve_emojis(guild, content)

    allowed = discord.AllowedMentions(
        roles=True,
        users=True,
        everyone=can_mention_everyone,
    )

    try:
        await target_channel.send(
            content=content or None,
            files=files,
            allowed_mentions=allowed,
        )
        return True, "Succès"
    except discord.Forbidden:
        return False, f"❌ Permissions insuffisantes pour envoyer un message dans {target_channel.mention}."
    except discord.HTTPException as e:
        logger.error(f"Erreur HTTP lors de la publication de l'annonce : {e}")
        return False, f"❌ Erreur lors de l'envoi du message : {e}"


class AnnouncementOptionsView(discord.ui.View):
    def __init__(self, source_message: discord.Message, author: discord.Member):
        super().__init__(timeout=120)
        self.source_message = source_message
        self.author = author
        self.target_channel = source_message.channel
        self.delete_original = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message(
                "❌ Seul l'initiateur de cette commande peut utiliser ces options.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.select(
        cls=discord.ui.ChannelSelect,
        channel_types=[discord.ChannelType.text],
        placeholder="Sélectionne le salon cible...",
        min_values=1,
        max_values=1,
        row=0,
    )
    async def select_channel(
        self, interaction: discord.Interaction, select: discord.ui.ChannelSelect
    ):
        self.target_channel = select.values[0]
        await interaction.response.edit_message(
            content=(
                f"📢 **Publication d'annonce**\n"
                f"• **Salon choisi :** {self.target_channel.mention}\n"
                f"• **Supprimer l'original :** {'Oui' if self.delete_original else 'Non'}"
            ),
            view=self,
        )

    @discord.ui.button(
        label="Supprimer l'original : Non",
        style=discord.ButtonStyle.secondary,
        row=1,
    )
    async def toggle_delete(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        self.delete_original = not self.delete_original
        button.label = f"Supprimer l'original : {'Oui' if self.delete_original else 'Non'}"
        button.style = (
            discord.ButtonStyle.danger
            if self.delete_original
            else discord.ButtonStyle.secondary
        )
        await interaction.response.edit_message(
            content=(
                f"📢 **Publication d'annonce**\n"
                f"• **Salon choisi :** {self.target_channel.mention}\n"
                f"• **Supprimer l'original :** {'Oui' if self.delete_original else 'Non'}"
            ),
            view=self,
        )

    @discord.ui.button(
        label="Publier l'annonce",
        style=discord.ButtonStyle.success,
        row=1,
    )
    async def confirm_publish(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await interaction.response.defer(ephemeral=True)

        target_channel_obj = interaction.guild.get_channel(self.target_channel.id)
        if not target_channel_obj:
            await interaction.followup.send(
                "❌ Salon cible introuvable.", ephemeral=True
            )
            return

        success, msg = await send_cloned_message(
            target_channel_obj,
            self.source_message,
            self.author,
            interaction.guild,
        )

        if not success:
            await interaction.followup.send(msg, ephemeral=True)
            return

        if (
            self.delete_original
            and self.source_message.channel.permissions_for(
                interaction.guild.me
            ).manage_messages
        ):
            try:
                await self.source_message.delete()
            except discord.HTTPException:
                pass

        await interaction.edit_original_response(
            content=f"✅ Annonce publiée avec succès dans {target_channel_obj.mention} !",
            view=None,
        )


class SayCog(commands.Cog, name="Say"):
    def __init__(self, bot):
        self.bot = bot
        self.ctx_menu = app_commands.ContextMenu(
            name="Publier en annonce",
            callback=self.context_publish_announcement,
        )
        self.ctx_menu.default_permissions = discord.Permissions(manage_guild=True)
        self.bot.tree.add_command(self.ctx_menu)

    async def cog_unload(self):
        self.bot.tree.remove_command(
            self.ctx_menu.name, type=self.ctx_menu.type
        )

    annonce_group = app_commands.Group(
        name="annonce",
        description="Publication d'annonces au nom du bot",
        default_permissions=discord.Permissions(manage_guild=True),
    )

    # -------------------------------------------------------------
    # 1. Commande Slash : Copier / Cloner un message
    # -------------------------------------------------------------
    @annonce_group.command(
        name="copier",
        description="Prend un message (texte + images) et le republie via le bot dans le salon cible.",
    )
    @can_manage()
    @app_commands.describe(
        salon="Salon où publier l'annonce",
        message_id="ID du message brouillon (laisser vide pour prendre votre dernier message)",
        supprimer_original="Supprimer le message brouillon après publication (Défaut: Non)",
    )
    async def say_clone(
        self,
        interaction: discord.Interaction,
        salon: discord.TextChannel,
        message_id: str = None,
        supprimer_original: bool = False,
    ):
        await interaction.response.defer(ephemeral=True)

        target_msg = None

        if message_id and message_id.isdigit():
            try:
                target_msg = await interaction.channel.fetch_message(
                    int(message_id)
                )
            except (discord.NotFound, discord.Forbidden):
                await interaction.followup.send(
                    "❌ Impossible de trouver ce message dans le salon actuel.",
                    ephemeral=True,
                )
                return
        else:
            async for msg in interaction.channel.history(limit=10):
                if msg.author == interaction.user:
                    target_msg = msg
                    break

        if not target_msg:
            await interaction.followup.send(
                "❌ Aucun message trouvé à copier.", ephemeral=True
            )
            return

        success, err_msg = await send_cloned_message(
            salon, target_msg, interaction.user, interaction.guild
        )
        if not success:
            await interaction.followup.send(err_msg, ephemeral=True)
            return

        if (
            supprimer_original
            and interaction.channel.permissions_for(
                interaction.guild.me
            ).manage_messages
        ):
            try:
                await target_msg.delete()
            except discord.HTTPException:
                pass

        await interaction.followup.send(
            f"✅ Annonce publiée avec succès dans {salon.mention} !",
            ephemeral=True,
        )

    # -------------------------------------------------------------
    # 2. Menu contextuel : Clic droit -> Applications -> Publier en annonce
    # -------------------------------------------------------------
    @app_commands.default_permissions(manage_guild=True)
    @can_manage()
    async def context_publish_announcement(
        self, interaction: discord.Interaction, message: discord.Message
    ):
        view = AnnouncementOptionsView(
            source_message=message, author=interaction.user
        )
        await interaction.response.send_message(
            content=(
                f"📢 **Publication d'annonce**\n"
                f"• **Salon choisi :** {interaction.channel.mention}\n"
                f"• **Supprimer l'original :** Non"
            ),
            view=view,
            ephemeral=True,
        )


async def setup(bot):
    await bot.add_cog(SayCog(bot))