import json
import logging
import re
import discord
from discord import app_commands
from discord.ext import commands
from db import fetchone, fetchall, execute
from utils.permissions import can_manage

logger = logging.getLogger("Conventions")

DEFAULT_CONVENTION_CHANNEL_ID = 1533849624366940219
DEFAULT_CONVENTION_CATEGORY_ID = 1533849624710746297


def resolve_mentions(guild: discord.Guild, text: str) -> str:
    """
    Remplace les mentions en texte brut comme @NomDuRole ou @PseudoMembre par de vraies balises <@&ID> ou <@ID>.
    Gère les espaces, les accents et l'insensibilité à la casse en testant les noms les plus longs en premier.
    """
    if not text or "@" not in text:
        return text

    # Résolution des rôles : triés par longueur décroissante du nom
    roles_by_length = sorted(
        [r for r in guild.roles if r.name != "@everyone"],
        key=lambda r: len(r.name),
        reverse=True,
    )
    for r in roles_by_length:
        pattern = rf"(?<!<@&)@{re.escape(r.name)}(?=[^a-zA-Z0-9À-ÿ]|$)"
        text = re.sub(pattern, f"<@&{r.id}>", text, flags=re.IGNORECASE)

    # Résolution des membres : triés par longueur décroissante du pseudo/nom
    members_by_length = sorted(
        guild.members,
        key=lambda m: max(len(m.display_name), len(m.name)),
        reverse=True,
    )
    for m in members_by_length:
        if m.display_name:
            pattern = rf"(?<!<@)@{re.escape(m.display_name)}(?=[^a-zA-Z0-9À-ÿ]|$)"
            text = re.sub(pattern, f"<@{m.id}>", text, flags=re.IGNORECASE)
        if m.name != m.display_name:
            pattern = rf"(?<!<@)@{re.escape(m.name)}(?=[^a-zA-Z0-9À-ÿ]|$)"
            text = re.sub(pattern, f"<@{m.id}>", text, flags=re.IGNORECASE)

    return text


def parse_convention_days(raw_input: str) -> tuple[list[str], list[str]]:
    """
    Découpe la saisie des jours et identifie les jours de rassemblement (* ou '(rassemblement)').
    Retourne (all_days, meetup_days).
    """
    days = []
    meetup_days = []
    for item in raw_input.split(","):
        cleaned = item.strip()
        if not cleaned:
            continue

        is_meetup = False
        if "*" in cleaned:
            is_meetup = True
            cleaned = cleaned.replace("*", "").strip()

        lower_cleaned = cleaned.lower()
        if "rassemblement" in lower_cleaned:
            is_meetup = True
            cleaned = re.sub(
                r"\(?\s*rassemblement\s*\)?", "", cleaned, flags=re.IGNORECASE
            ).strip()

        if cleaned:
            day_formatted = (
                cleaned[0].upper() + cleaned[1:]
                if len(cleaned) > 1
                else cleaned.upper()
            )
            if day_formatted not in days:
                days.append(day_formatted)
                if is_meetup and day_formatted not in meetup_days:
                    meetup_days.append(day_formatted)

    return days, meetup_days


def split_message_content(text: str, max_chars: int = 1950) -> list[str]:
    """
    Découpe un texte en plusieurs morceaux de taille inférieure ou égale à max_chars,
    en privilégiant les coupures sur les sauts de ligne ou les espaces pour ne pas tronquer les phrases.
    """
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    chunks = []
    remaining = text
    while len(remaining) > max_chars:
        split_idx = remaining.rfind("\n\n", 0, max_chars)
        if split_idx == -1 or split_idx < max_chars // 2:
            split_idx = remaining.rfind("\n", 0, max_chars)
        if split_idx == -1 or split_idx < max_chars // 2:
            split_idx = remaining.rfind(" ", 0, max_chars)
        if split_idx == -1:
            split_idx = max_chars

        chunks.append(remaining[:split_idx].strip())
        remaining = remaining[split_idx:].strip()

    if remaining:
        chunks.append(remaining)

    return chunks


def slugify_channel_name(name: str) -> str:
    """Génère un nom de salon Discord propre à partir du nom de la convention."""
    cleaned = re.sub(r"[^a-zA-Z0-9à-ÿÀ-Ý]+", "-", name.lower()).strip("-")
    return f"🎭・{cleaned}"[:100]


def build_convention_embed(
    convention: dict,
    participants: list[dict],
    role: discord.Role | None,
    guild: discord.Guild | None = None,
) -> discord.Embed:
    """Construit l'Embed de la convention avec le salon dédié, les rassemblements et les présences."""
    title = convention["title"]
    location = convention["location"]
    days_list = json.loads(convention["days_json"])
    meetup_days = json.loads(convention.get("meetup_days_json") or "[]")
    dedicated_channel_id = convention.get("dedicated_channel_id")

    embed = discord.Embed(
        title=f"🎭 {title}",
        color=discord.Color.from_rgb(203, 166, 247),
        timestamp=discord.utils.utcnow(),
    )

    embed.description = "ℹ️ *Cliquez sur les boutons ci-dessous pour indiquer vos jours de présence et accéder au salon dédié !*"
    embed.add_field(name="📍 Lieu", value=f"**{location}**", inline=False)

    if meetup_days:
        meetups_str = ", ".join(f"⭐ **{d}**" for d in meetup_days)
        embed.add_field(
            name="👥 Rassemblement(s) du groupe",
            value=meetups_str,
            inline=False,
        )

    if dedicated_channel_id:
        embed.add_field(
            name="💬 Salon d'échange",
            value=f"<#{dedicated_channel_id}>",
            inline=False,
        )

    # Répartition des participants par jour
    for day in days_list:
        day_parts = [p for p in participants if p["day_name"] == day]
        count = len(day_parts)
        if day_parts:
            members_list = "\n".join(f"• <@{p['user_id']}>" for p in day_parts)
        else:
            members_list = "*(Aucun participant pour le moment)*"

        is_meetup = day in meetup_days
        badge = " ⭐ Rassemblement" if is_meetup else ""
        embed.add_field(
            name=f"📅 {day}{badge} ({count})",
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

    # Décompte unique des participants confirmés possédant le rôle (exclut absents et réflexion)
    active_user_ids = {
        p["user_id"]
        for p in participants
        if p["day_name"] not in ("__absent__", "__maybe__")
    }

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
    embed = build_convention_embed(conv, participants, role, guild)

    try:
        await message.edit(embed=embed, view=view)
    except discord.HTTPException as e:
        logger.error(
            f"Erreur lors de la mise à jour de l'embed convention #{conv_id} : {e}"
        )


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
            await interaction.followup.send(
                "❌ Cette convention n'existe plus.", ephemeral=True
            )
            return

        main_role = guild.get_role(int(conv["role_id"]))
        meetup_roles_map = json.loads(conv.get("meetup_roles_json") or "{}")
        dedicated_ch_id = conv.get("dedicated_channel_id")
        ch_mention = (
            f"<#{dedicated_ch_id}>"
            if dedicated_ch_id
            else "le salon de la convention"
        )

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

            # Si ce jour est un rassemblement, retirer le rôle de rassemblement spécifique
            if self.day_name in meetup_roles_map:
                m_role_id = meetup_roles_map[self.day_name]
                m_role = guild.get_role(int(m_role_id))
                if m_role and m_role in user.roles:
                    try:
                        await user.remove_roles(
                            m_role,
                            reason=f"Désinscription rassemblement {self.day_name}",
                        )
                    except discord.HTTPException:
                        pass

            # Vérifier s'il reste d'autres jours pour cet utilisateur
            remaining = await fetchall(
                "SELECT id FROM convention_participants WHERE convention_id=%s AND user_id=%s AND day_name NOT IN ('__absent__', '__maybe__')",
                (self.conv_id, user.id),
            )

            if not remaining:
                if main_role and main_role in user.roles:
                    try:
                        await user.remove_roles(
                            main_role,
                            reason="Désinscription totale de la convention",
                        )
                    except discord.HTTPException:
                        pass

                # Retirer tous les rôles de rassemblement restants par sécurité
                for r_id in meetup_roles_map.values():
                    r_obj = guild.get_role(int(r_id))
                    if r_obj and r_obj in user.roles:
                        try:
                            await user.remove_roles(r_obj)
                        except discord.HTTPException:
                            pass

                msg = f"❌ Tu t'es désinscrit(e) pour le **{self.day_name}**.\nN'ayant plus aucun jour sélectionné, tu n'as plus accès à {ch_mention}."
            else:
                msg = f"❌ Tu t'es désinscrit(e) pour le **{self.day_name}** (tu conserves l'accès à {ch_mention} pour tes autres jours)."
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

            # Attribution du rôle principal (accès au salon) si pas déjà possédé
            if main_role and main_role not in user.roles:
                try:
                    await user.add_roles(
                        main_role, reason="Inscription à la convention"
                    )
                except discord.HTTPException:
                    pass

            # Si ce jour est un rassemblement, attribuer le rôle de rassemblement spécifique
            if self.day_name in meetup_roles_map:
                m_role_id = meetup_roles_map[self.day_name]
                m_role = guild.get_role(int(m_role_id))
                if m_role and m_role not in user.roles:
                    try:
                        await user.add_roles(
                            m_role,
                            reason=f"Inscription rassemblement {self.day_name}",
                        )
                    except discord.HTTPException:
                        pass

            extra_info = ""
            if self.day_name in meetup_roles_map:
                extra_info = f"\n⭐ Tu as également reçu le rôle de rassemblement pour le **{self.day_name}** !"

            msg = f"✅ Tu es inscrit(e) pour le **{self.day_name}** ! Tu as désormais accès au salon {ch_mention}.{extra_info}"

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
            await interaction.followup.send(
                "❌ Cette convention n'existe plus.", ephemeral=True
            )
            return

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

        # Retrait du rôle principal
        main_role = guild.get_role(int(conv["role_id"]))
        if main_role and main_role in user.roles:
            try:
                await user.remove_roles(
                    main_role, reason="Indication de réflexion convention"
                )
            except discord.HTTPException:
                pass

        # Retrait de tous les rôles de rassemblement
        meetup_roles_map = json.loads(conv.get("meetup_roles_json") or "{}")
        for r_id in meetup_roles_map.values():
            r_obj = guild.get_role(int(r_id))
            if r_obj and r_obj in user.roles:
                try:
                    await user.remove_roles(r_obj)
                except discord.HTTPException:
                    pass

        msg = (
            "💭 Tu as indiqué être en réflexion pour cette convention.\n"
            "Tes choix de présence ont été réinitialisés et tes accès ont été suspendus en attendant ta décision !"
        )

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
            await interaction.followup.send(
                "❌ Cette convention n'existe plus.", ephemeral=True
            )
            return

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

        # Retrait du rôle principal
        main_role = guild.get_role(int(conv["role_id"]))
        if main_role and main_role in user.roles:
            try:
                await user.remove_roles(
                    main_role, reason="Indication d'absence convention"
                )
            except discord.HTTPException:
                pass

        # Retrait de tous les rôles de rassemblement
        meetup_roles_map = json.loads(conv.get("meetup_roles_json") or "{}")
        for r_id in meetup_roles_map.values():
            r_obj = guild.get_role(int(r_id))
            if r_obj and r_obj in user.roles:
                try:
                    await user.remove_roles(r_obj)
                except discord.HTTPException:
                    pass

        msg = (
            "❌ Tu as indiqué ne pas venir. Tes choix ont été réinitialisés "
            "et tes accès à la convention ont été retirés."
        )

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
    role_prefix = discord.ui.TextInput(
        label="Préfixe du rôle",
        placeholder="Ex: Japan Expo",
        required=True,
        max_length=100,
    )
    lieu = discord.ui.TextInput(
        label="Lieu / Ville",
        placeholder="Ex: Parc des Expositions Villepinte",
        required=True,
        max_length=100,
    )
    jours = discord.ui.TextInput(
        label="Jours de convention (* = rassemblement)",
        placeholder="Ex: Jeudi, Vendredi, Samedi*, Dimanche",
        required=True,
        max_length=150,
    )
    annonce = discord.ui.TextInput(
        label="Texte d'annonce (Markdown & mentions)",
        style=discord.TextStyle.paragraph,
        placeholder="Ex: **Préparez vos cosplays !** @everyone\nRassemblement prévu le samedi !",
        required=False,
        max_length=4000,
    )

    def __init__(self, bot, target_channel: discord.TextChannel):
        super().__init__()
        self.bot = bot
        self.target_channel = target_channel

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild

        # Découpage et identification des jours et rassemblements (*)
        days, meetup_days = parse_convention_days(self.jours.value)
        if not days:
            await interaction.followup.send(
                "❌ Vous devez indiquer au moins un jour valide (séparés par des virgules).",
                ephemeral=True,
            )
            return

        if len(days) > 15:
            await interaction.followup.send(
                "❌ Limite de 15 jours par événement dépassée.", ephemeral=True
            )
            return

        prefix = self.role_prefix.value.strip()

        # 1. Création automatique du rôle principal (accès au salon)
        try:
            main_role = await guild.create_role(
                name=prefix,
                color=discord.Color.from_rgb(203, 166, 247),
                mentionable=True,
                reason=f"Rôle principal créé pour la convention {self.titre.value.strip()} par {interaction.user.display_name}",
            )
        except discord.Forbidden:
            await interaction.followup.send(
                "❌ Le bot n'a pas la permission de créer des rôles (`manage_roles`).",
                ephemeral=True,
            )
            return
        except discord.HTTPException as e:
            await interaction.followup.send(
                f"❌ Erreur lors de la création du rôle principal : {e}",
                ephemeral=True,
            )
            return

        # 2. Création automatique des rôles de rassemblement
        meetup_roles = {}
        created_roles = [main_role]
        for m_day in meetup_days:
            r_name = f"{prefix} - Rassemblement {m_day}"[:100]
            try:
                m_role = await guild.create_role(
                    name=r_name,
                    color=discord.Color.from_rgb(249, 226, 175),
                    mentionable=True,
                    reason=f"Rôle de rassemblement pour {self.titre.value.strip()} ({m_day})",
                )
                meetup_roles[m_day] = m_role.id
                created_roles.append(m_role)
            except discord.HTTPException as e:
                # Nettoyage en cas d'échec
                for r in created_roles:
                    try:
                        await r.delete()
                    except discord.HTTPException:
                        pass
                await interaction.followup.send(
                    f"❌ Erreur lors de la création du rôle de rassemblement ({m_day}) : {e}",
                    ephemeral=True,
                )
                return

        # 3. Création du salon dédié dans la catégorie configurée
        category = guild.get_channel(DEFAULT_CONVENTION_CATEGORY_ID)
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            main_role: discord.PermissionOverwrite(
                view_channel=True, send_messages=True
            ),
            guild.me: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, manage_channels=True
            ),
        }

        channel_name = slugify_channel_name(self.titre.value.strip())
        try:
            dedicated_channel = await guild.create_text_channel(
                name=channel_name,
                category=(
                    category
                    if isinstance(category, discord.CategoryChannel)
                    else None
                ),
                overwrites=overwrites,
                topic=f"Salon officiel de la convention {self.titre.value.strip()} - Lieu: {self.lieu.value.strip()}",
                reason=f"Salon convention créé par {interaction.user.display_name}",
            )
        except (discord.Forbidden, discord.HTTPException) as e:
            for r in created_roles:
                try:
                    await r.delete()
                except discord.HTTPException:
                    pass
            await interaction.followup.send(
                f"❌ Impossible de créer le salon dédié dans la catégorie : {e}",
                ephemeral=True,
            )
            return

        # Message d'accueil dans le salon dédié
        meetups_str = (
            ", ".join(meetup_days)
            if meetup_days
            else "Aucun rassemblement officiel spécifié"
        )
        welcome_embed = discord.Embed(
            title=f"🎭 Salon officiel : {self.titre.value.strip()}",
            description=(
                f"📍 **Lieu :** {self.lieu.value.strip()}\n"
                f"📅 **Jours de la convention :** {', '.join(days)}\n"
                f"👥 **Rassemblement(s) du groupe :** {meetups_str}\n\n"
                f"Ce salon est réservé aux membres possédant le rôle {main_role.mention}.\n"
                f"Échangez ici sur vos préparatifs, cosplays, covoiturages et photos !"
            ),
            color=discord.Color.from_rgb(203, 166, 247),
        )
        try:
            await dedicated_channel.send(
                content=f"👋 Bienvenue à tous {main_role.mention} !",
                embed=welcome_embed,
            )
        except discord.HTTPException:
            pass

        # 4. Résolution intelligente des mentions dans le texte d'annonce et découpage si > 1950 caractères
        raw_annonce = (
            self.annonce.value.strip()
            if (self.annonce.value and self.annonce.value.strip())
            else ""
        )
        resolved_annonce = (
            resolve_mentions(guild, raw_annonce) if raw_annonce else ""
        )
        chunks = (
            split_message_content(resolved_annonce, max_chars=1950)
            if resolved_annonce
            else []
        )

        allowed = discord.AllowedMentions(
            everyone=interaction.user.guild_permissions.mention_everyone,
            roles=True,
            users=True,
        )

        extra_msg_ids = []
        if len(chunks) > 1:
            try:
                for c in chunks[:-1]:
                    extra_m = await self.target_channel.send(
                        content=c, allowed_mentions=allowed
                    )
                    extra_msg_ids.append(extra_m.id)
                main_content = chunks[-1]
            except (discord.Forbidden, discord.HTTPException) as e:
                for mid in extra_msg_ids:
                    try:
                        m = await self.target_channel.fetch_message(mid)
                        await m.delete()
                    except discord.HTTPException:
                        pass
                for r in created_roles:
                    try:
                        await r.delete()
                    except discord.HTTPException:
                        pass
                try:
                    await dedicated_channel.delete()
                except discord.HTTPException:
                    pass
                await interaction.followup.send(
                    f"❌ Impossible d'envoyer l'annonce dans {self.target_channel.mention} : {e}",
                    ephemeral=True,
                )
                return
        elif len(chunks) == 1:
            main_content = chunks[0]
        else:
            main_content = None

        days_json = json.dumps(days, ensure_ascii=False)
        meetup_days_json = json.dumps(meetup_days, ensure_ascii=False)
        meetup_roles_json = json.dumps(meetup_roles, ensure_ascii=False)
        extra_messages_json = json.dumps(extra_msg_ids, ensure_ascii=False)

        # 5. Enregistrement en base de données
        conv_id = await execute(
            """
            INSERT INTO conventions (
                guild_id, channel_id, message_id, role_id, title, role_name, role_prefix,
                location, description, days_json, dedicated_channel_id, meetup_days_json, meetup_roles_json, extra_messages_json
            ) VALUES (%s, %s, 0, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                guild.id,
                self.target_channel.id,
                main_role.id,
                self.titre.value.strip(),
                prefix,
                prefix,
                self.lieu.value.strip(),
                resolved_annonce,
                days_json,
                dedicated_channel.id,
                meetup_days_json,
                meetup_roles_json,
                extra_messages_json,
            ),
        )

        conv_data = {
            "id": conv_id,
            "title": self.titre.value.strip(),
            "location": self.lieu.value.strip(),
            "description": resolved_annonce,
            "role_id": main_role.id,
            "days_json": days_json,
            "dedicated_channel_id": dedicated_channel.id,
            "meetup_days_json": meetup_days_json,
            "meetup_roles_json": meetup_roles_json,
            "extra_messages_json": extra_messages_json,
        }

        # 6. Création de l'Embed et publication de l'annonce interactive
        embed = build_convention_embed(conv_data, [], main_role, guild)
        view = ConventionView(conv_id, days)

        try:
            msg = await self.target_channel.send(
                content=main_content,
                embed=embed,
                view=view,
                allowed_mentions=allowed,
            )
        except (discord.Forbidden, discord.HTTPException) as e:
            for mid in extra_msg_ids:
                try:
                    m = await self.target_channel.fetch_message(mid)
                    await m.delete()
                except discord.HTTPException:
                    pass
            await execute("DELETE FROM conventions WHERE id=%s", (conv_id,))
            for r in created_roles:
                try:
                    await r.delete()
                except discord.HTTPException:
                    pass
            try:
                await dedicated_channel.delete()
            except discord.HTTPException:
                pass
            await interaction.followup.send(
                f"❌ Impossible d'envoyer le message interactif dans {self.target_channel.mention} : {e}",
                ephemeral=True,
            )
            return

        # Mise à jour de l'ID du message en BDD et persistance
        await execute(
            "UPDATE conventions SET message_id=%s WHERE id=%s",
            (msg.id, conv_id),
        )
        self.bot.add_view(view, message_id=msg.id)

        roles_summary = f"🎟️ Rôle principal : {main_role.mention}"
        if meetup_roles:
            m_mentions = ", ".join(
                f"<@&{rid}> ({d})" for d, rid in meetup_roles.items()
            )
            roles_summary += f"\n⭐ Rôle(s) de rassemblement : {m_mentions}"

        await interaction.followup.send(
            f"✅ Convention **{self.titre.value.strip()}** créée avec succès !\n"
            f"📢 Annonce publiée dans : {self.target_channel.mention}\n"
            f"💬 Salon dédié créé : {dedicated_channel.mention}\n"
            f"{roles_summary}",
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
        if (
            not current_lower
            or current_lower in label.lower()
            or current_lower in str(r["id"])
        ):
            choices.append(app_commands.Choice(name=label, value=r["id"]))
    return choices[:25]


class ConventionsCog(commands.Cog, name="Conventions"):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        """Réenregistre toutes les vues persistantes des conventions lors du démarrage."""
        try:
            rows = await fetchall(
                "SELECT id, days_json, message_id FROM conventions", ()
            )
            for r in rows:
                if r.get("message_id") and r.get("days_json"):
                    days = json.loads(r["days_json"])
                    view = ConventionView(r["id"], days)
                    self.bot.add_view(view, message_id=int(r["message_id"]))
            logger.info(
                f"✅ {len(rows)} vue(s) persistante(s) de convention réenregistrée(s)."
            )
        except Exception as e:
            logger.warning(
                f"Impossible de réenregistrer les vues de convention : {e}"
            )

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        """Nettoie les présences des membres quittant le serveur."""
        try:
            await execute(
                "DELETE FROM convention_participants WHERE user_id=%s",
                (member.id,),
            )
        except Exception as e:
            logger.error(
                f"Erreur lors du nettoyage des conventions pour le membre {member.id} : {e}"
            )

    convention_group = app_commands.Group(
        name="convention",
        description="Organisation des conventions et événements cosplay",
        default_permissions=discord.Permissions(manage_guild=True),
    )

    @convention_group.command(
        name="creer",
        description="Créer une nouvelle convention avec sélection de jours, rassemblements et salon dédié.",
    )
    @can_manage()
    @app_commands.describe(
        salon="Salon d'affichage de l'annonce (optionnel, par défaut salon officiel)"
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
        description="Clôturer une convention, supprimer le salon dédié, les rôles et nettoyer la BDD.",
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

        # 1. Supprimer le salon dédié dans la catégorie
        ded_channel_id = conv.get("dedicated_channel_id")
        if ded_channel_id:
            ded_ch = interaction.guild.get_channel(int(ded_channel_id))
            if ded_ch:
                try:
                    await ded_ch.delete(
                        reason=f"Archivage de la convention #{conv['id']}"
                    )
                except discord.HTTPException:
                    pass

        # 2. Supprimer le rôle principal
        main_role = interaction.guild.get_role(int(conv["role_id"]))
        if main_role:
            try:
                await main_role.delete(
                    reason=f"Archivage de la convention #{conv['id']}"
                )
            except discord.HTTPException:
                pass

        # 3. Supprimer les rôles de rassemblement
        meetup_roles_map = json.loads(conv.get("meetup_roles_json") or "{}")
        for r_id in meetup_roles_map.values():
            r_obj = interaction.guild.get_role(int(r_id))
            if r_obj:
                try:
                    await r_obj.delete(
                        reason=f"Archivage rôle de rassemblement #{conv['id']}"
                    )
                except discord.HTTPException:
                    pass

        # 4. Supprimer les messages d'annonce (principal et préliminaires)
        channel = interaction.guild.get_channel(int(conv["channel_id"]))
        if channel:
            extra_msg_ids = json.loads(conv.get("extra_messages_json") or "[]")
            for mid in extra_msg_ids:
                try:
                    m = await channel.fetch_message(int(mid))
                    await m.delete()
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    pass
            try:
                msg = await channel.fetch_message(int(conv["message_id"]))
                await msg.delete()
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass

        # 5. Supprimer de la BDD
        await execute(
            "DELETE FROM convention_participants WHERE convention_id=%s",
            (convention_id,),
        )
        await execute("DELETE FROM conventions WHERE id=%s", (convention_id,))

        await interaction.followup.send(
            f"🗑️ La convention **{conv['title']}**, son salon dédié et tous ses rôles associés ont été archivés et supprimés avec succès.",
            ephemeral=True,
        )

    @convention_group.command(
        name="liste",
        description="Lister toutes les conventions actives sur le serveur.",
    )
    @can_manage()
    async def lister_conventions(self, interaction: discord.Interaction):
        rows = await fetchall(
            "SELECT id, title, location, channel_id, dedicated_channel_id, role_id FROM conventions WHERE guild_id=%s ORDER BY id DESC",
            (interaction.guild_id,),
        )
        if not rows:
            await interaction.response.send_message(
                "ℹ️ Aucune convention enregistrée sur ce serveur.",
                ephemeral=True,
            )
            return

        lines = []
        for r in rows:
            salon_ded = (
                f"<#{r['dedicated_channel_id']}>"
                if r.get("dedicated_channel_id")
                else "*(Aucun)*"
            )
            lines.append(
                f"• `#{r['id']}` **{r['title']}** (Lieu: {r['location']})\n"
                f"  └ Annonce: <#{r['channel_id']}> | Salon dédié: {salon_ded} | Rôle: <@&{r['role_id']}>"
            )

        embed = discord.Embed(
            title="🎭 Conventions Cosplay Actives",
            description="\n".join(lines),
            color=discord.Color.from_rgb(180, 190, 254),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(ConventionsCog(bot))
