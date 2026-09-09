import asyncio
import logging
from datetime import timedelta
import discord
from discord.ext import commands
from db import get_guild_settings

logger = logging.getLogger("Logs")


class LogsCog(commands.Cog, name="Logs"):
    def __init__(self, bot):
        self.bot = bot

    async def _get_log_channel(self, guild: discord.Guild) -> discord.TextChannel | None:
        if not guild:
            return None
        settings = await get_guild_settings(guild.id)
        log_channel_id = settings.get("log_channel_id")
        if not log_channel_id:
            return None
        return guild.get_channel(int(log_channel_id))

    # -------------------------------------------------------------
    # 1. MESSAGES (Suppression, Purge, Modification)
    # -------------------------------------------------------------

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent):
        if not payload.guild_id:
            return

        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return

        log_channel = await self._get_log_channel(guild)
        if not log_channel:
            return

        channel = guild.get_channel(payload.channel_id)
        cached_message = payload.cached_message

        # Ignorer si le message vient d'un bot
        if cached_message and cached_message.author and cached_message.author.bot:
            return

        # Laisser le temps à Discord de pousser l'entrée dans les Audit Logs
        await asyncio.sleep(0.8)

        deleted_by = None

        if guild.me.guild_permissions.view_audit_log:
            try:
                now = discord.utils.utcnow()
                async for entry in guild.audit_logs(
                    limit=5, action=discord.AuditLogAction.message_delete
                ):
                    entry_channel = getattr(
                        getattr(entry, "extra", None), "channel", None
                    )
                    entry_channel_id = getattr(entry_channel, "id", None)

                    if (
                        entry_channel_id == payload.channel_id
                        and abs((now - entry.created_at).total_seconds()) <= 10
                    ):
                        if entry.user:
                            deleted_by = f"{entry.user.mention} (`{entry.user.display_name}`)"
                        break
            except (discord.Forbidden, discord.HTTPException):
                pass

        if not deleted_by:
            if cached_message and cached_message.author:
                deleted_by = (
                    f"L'auteur lui-même ({cached_message.author.mention})"
                )
            else:
                deleted_by = "Inconnu / L'auteur lui-même"

        author_str = (
            cached_message.author.mention
            if (cached_message and cached_message.author)
            else "Non mis en cache"
        )
        content_str = (
            (
                cached_message.content[:1024]
                if cached_message.content
                else "*(Contenu non textuel ou média)*"
            )
            if cached_message
            else "*(Message non présent dans le cache du bot)*"
        )
        channel_str = (
            channel.mention if channel else f"<#{payload.channel_id}>"
        )

        embed = discord.Embed(
            title="🗑️ Message supprimé",
            color=discord.Color.red(),
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="Auteur", value=author_str, inline=True)
        embed.add_field(name="Supprimé par", value=deleted_by, inline=True)
        embed.add_field(name="Salon", value=channel_str, inline=True)
        embed.add_field(name="Contenu", value=content_str, inline=False)
        embed.set_footer(text=f"ID Message : {payload.message_id}")

        try:
            await log_channel.send(embed=embed)
        except discord.HTTPException:
            pass

    @commands.Cog.listener()
    async def on_bulk_message_delete(self, messages: list[discord.Message]):
        if not messages:
            return
        log_channel = await self._get_log_channel(messages[0].guild)
        if not log_channel:
            return

        embed = discord.Embed(
            title=f"🧹 Purge de messages ({len(messages)} supprimés)",
            description=f"**Salon :** {messages[0].channel.mention}",
            color=discord.Color.orange(),
            timestamp=discord.utils.utcnow(),
        )

        for msg in reversed(messages[:10]):
            content_str = (
                msg.content[:200] if msg.content else "*(Média/Non textuel)*"
            )
            embed.add_field(
                name=f"De {msg.author.display_name if msg.author else 'Inconnu'}",
                value=content_str,
                inline=False,
            )

        if len(messages) > 10:
            embed.set_footer(
                text=f"Et {len(messages) - 10} autre(s) message(s) supprimé(s)..."
            )

        try:
            await log_channel.send(embed=embed)
        except discord.HTTPException:
            pass

    @commands.Cog.listener()
    async def on_message_edit(
        self, before: discord.Message, after: discord.Message
    ):
        if (
            (before.author and before.author.bot)
            or before.content == after.content
        ):
            return
        log_channel = await self._get_log_channel(before.guild)
        if not log_channel:
            return

        embed = discord.Embed(
            title="✏️ Message modifié",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(
            name="Auteur",
            value=before.author.mention if before.author else "Inconnu",
            inline=True,
        )
        embed.add_field(
            name="Salon",
            value=before.channel.mention if before.channel else "Inconnu",
            inline=True,
        )
        embed.add_field(
            name="Avant",
            value=before.content[:1024] if before.content else "*(vide)*",
            inline=False,
        )
        embed.add_field(
            name="Après",
            value=after.content[:1024] if after.content else "*(vide)*",
            inline=False,
        )

        try:
            await log_channel.send(embed=embed)
        except discord.HTTPException:
            pass

    # -------------------------------------------------------------
    # 2. MEMBRES & MODÉRATION (Arrivée, Départ/Kick, Bans, Pseudo, Rôles, Timeout)
    # -------------------------------------------------------------

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        log_channel = await self._get_log_channel(member.guild)
        if not log_channel:
            return

        embed = discord.Embed(
            title="📥 Membre rejoint",
            description=f"{member.mention} (`{member.display_name}`) a rejoint le serveur.",
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow(),
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text=f"ID Membre : {member.id}")

        try:
            await log_channel.send(embed=embed)
        except discord.HTTPException:
            pass

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        log_channel = await self._get_log_channel(member.guild)
        if not log_channel:
            return

        # 1. Vérification si le départ est dû à un BAN
        if member.guild.me.guild_permissions.ban_members:
            try:
                ban_entry = await member.guild.fetch_ban(member)
                if ban_entry:
                    return
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass

        # 2. Vérification si le départ est un KICK
        is_kick = False
        kicked_by = None
        kick_reason = None

        if member.guild.me.guild_permissions.view_audit_log:
            now = discord.utils.utcnow()
            try:
                async for entry in member.guild.audit_logs(
                    limit=5, action=discord.AuditLogAction.kick
                ):
                    if (
                        entry.target
                        and entry.target.id == member.id
                        and (now - entry.created_at) <= timedelta(seconds=6)
                    ):
                        is_kick = True
                        kicked_by = entry.user
                        kick_reason = entry.reason
                        break
            except (discord.Forbidden, discord.HTTPException):
                pass

        if is_kick:
            embed = discord.Embed(
                title="👢 Membre expulsé (Kick)",
                description=f"**{member.display_name}** ({member.mention}) a été expulsé du serveur.",
                color=discord.Color.orange(),
                timestamp=discord.utils.utcnow(),
            )
            embed.add_field(
                name="Expulsé par",
                value=kicked_by.mention if kicked_by else "Inconnu",
                inline=True,
            )
            if kick_reason:
                embed.add_field(name="Motif", value=kick_reason, inline=False)
        else:
            embed = discord.Embed(
                title="📤 Départ volontaire",
                description=f"**{member.display_name}** ({member.mention}) a quitté le serveur.",
                color=discord.Color.dark_grey(),
                timestamp=discord.utils.utcnow(),
            )

        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text=f"ID Membre : {member.id}")

        try:
            await log_channel.send(embed=embed)
        except discord.HTTPException:
            pass

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User):
        log_channel = await self._get_log_channel(guild)
        if not log_channel:
            return

        banned_by = None
        ban_reason = None

        if guild.me.guild_permissions.view_audit_log:
            now = discord.utils.utcnow()
            try:
                async for entry in guild.audit_logs(
                    limit=5, action=discord.AuditLogAction.ban
                ):
                    if (
                        entry.target
                        and entry.target.id == user.id
                        and (now - entry.created_at) <= timedelta(seconds=6)
                    ):
                        banned_by = entry.user
                        ban_reason = entry.reason
                        break
            except (discord.Forbidden, discord.HTTPException):
                pass

        embed = discord.Embed(
            title="🔨 Membre banni",
            description=f"**{user.display_name}** (`{user.id}`) a été banni du serveur.",
            color=discord.Color.dark_red(),
            timestamp=discord.utils.utcnow(),
        )
        if banned_by:
            embed.add_field(
                name="Banni par", value=banned_by.mention, inline=True
            )
        if ban_reason:
            embed.add_field(name="Motif", value=ban_reason, inline=False)

        try:
            await log_channel.send(embed=embed)
        except discord.HTTPException:
            pass

    @commands.Cog.listener()
    async def on_member_unban(self, guild: discord.Guild, user: discord.User):
        log_channel = await self._get_log_channel(guild)
        if not log_channel:
            return

        unbanned_by = None
        if guild.me.guild_permissions.view_audit_log:
            now = discord.utils.utcnow()
            try:
                async for entry in guild.audit_logs(
                    limit=5, action=discord.AuditLogAction.unban
                ):
                    if (
                        entry.target
                        and entry.target.id == user.id
                        and (now - entry.created_at) <= timedelta(seconds=6)
                    ):
                        unbanned_by = entry.user
                        break
            except (discord.Forbidden, discord.HTTPException):
                pass

        embed = discord.Embed(
            title="🔓 Bannissement annulé",
            description=f"**{user.display_name}** (`{user.id}`) a été débanni.",
            color=discord.Color.teal(),
            timestamp=discord.utils.utcnow(),
        )
        if unbanned_by:
            embed.add_field(
                name="Débanni par", value=unbanned_by.mention, inline=True
            )

        try:
            await log_channel.send(embed=embed)
        except discord.HTTPException:
            pass

    @commands.Cog.listener()
    async def on_member_update(
        self, before: discord.Member, after: discord.Member
    ):
        log_channel = await self._get_log_channel(after.guild)
        if not log_channel:
            return

        # Pseudo / Nom d'affichage
        if before.display_name != after.display_name:
            embed = discord.Embed(
                title="👤 Pseudo modifié",
                description=f"{after.mention} a changé de nom d'affichage.",
                color=discord.Color.gold(),
                timestamp=discord.utils.utcnow(),
            )
            embed.add_field(
                name="Avant", value=before.display_name, inline=True
            )
            embed.add_field(name="Après", value=after.display_name, inline=True)
            try:
                await log_channel.send(embed=embed)
            except discord.HTTPException:
                pass

        # Modification des Rôles
        if before.roles != after.roles:
            added = [r.mention for r in after.roles if r not in before.roles]
            removed = [r.mention for r in before.roles if r not in after.roles]

            if added or removed:
                updated_by = None
                if after.guild.me.guild_permissions.view_audit_log:
                    now = discord.utils.utcnow()
                    try:
                        async for entry in after.guild.audit_logs(
                            limit=5,
                            action=discord.AuditLogAction.member_role_update,
                        ):
                            if (
                                entry.target
                                and entry.target.id == after.id
                                and (now - entry.created_at)
                                <= timedelta(seconds=6)
                            ):
                                updated_by = entry.user
                                break
                    except (discord.Forbidden, discord.HTTPException):
                        pass

                embed = discord.Embed(
                    title="🎟️ Rôles mis à jour",
                    description=f"Mise à jour des rôles pour {after.mention}.",
                    color=discord.Color.purple(),
                    timestamp=discord.utils.utcnow(),
                )
                if updated_by:
                    embed.add_field(
                        name="Modifié par",
                        value=updated_by.mention,
                        inline=False,
                    )
                if added:
                    embed.add_field(
                        name="Rôle(s) ajouté(s)",
                        value=", ".join(added),
                        inline=False,
                    )
                if removed:
                    embed.add_field(
                        name="Rôle(s) retiré(s)",
                        value=", ".join(removed),
                        inline=False,
                    )
                try:
                    await log_channel.send(embed=embed)
                except discord.HTTPException:
                    pass

        # Exclusion temporaire (Timeout)
        if before.timed_out_until != after.timed_out_until:
            timeout_by = None
            timeout_reason = None
            if after.guild.me.guild_permissions.view_audit_log:
                now = discord.utils.utcnow()
                try:
                    async for entry in after.guild.audit_logs(
                        limit=5, action=discord.AuditLogAction.member_update
                    ):
                        if (
                            entry.target
                            and entry.target.id == after.id
                            and (now - entry.created_at) <= timedelta(seconds=6)
                        ):
                            timeout_by = entry.user
                            timeout_reason = entry.reason
                            break
                except (discord.Forbidden, discord.HTTPException):
                    pass

            embed = discord.Embed(
                title="⏳ Exclusion temporaire (Timeout)",
                color=discord.Color.orange(),
                timestamp=discord.utils.utcnow(),
            )

            if after.timed_out_until:
                embed.description = f"{after.mention} a été mis en sourdine jusqu'au <t:{int(after.timed_out_until.timestamp())}:F>."
            else:
                embed.description = (
                    f"La mise en sourdine de {after.mention} a été retirée."
                )

            if timeout_by:
                embed.add_field(
                    name="Modérateur", value=timeout_by.mention, inline=True
                )
            if timeout_reason:
                embed.add_field(name="Motif", value=timeout_reason, inline=False)

            try:
                await log_channel.send(embed=embed)
            except discord.HTTPException:
                pass

    # -------------------------------------------------------------
    # 3. SALONS & CATÉGORIES (Création, Suppression)
    # -------------------------------------------------------------

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel):
        log_channel = await self._get_log_channel(channel.guild)
        if not log_channel:
            return

        created_by = None
        if channel.guild.me.guild_permissions.view_audit_log:
            now = discord.utils.utcnow()
            try:
                async for entry in channel.guild.audit_logs(
                    limit=5, action=discord.AuditLogAction.channel_create
                ):
                    if (
                        entry.target
                        and entry.target.id == channel.id
                        and (now - entry.created_at) <= timedelta(seconds=6)
                    ):
                        created_by = entry.user
                        break
            except (discord.Forbidden, discord.HTTPException):
                pass

        embed = discord.Embed(
            title="📁 Salon créé",
            description=f"Le salon {channel.mention} (`{channel.name}`) a été créé.",
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow(),
        )
        if created_by:
            embed.add_field(
                name="Créé par", value=created_by.mention, inline=True
            )

        try:
            await log_channel.send(embed=embed)
        except discord.HTTPException:
            pass

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel):
        log_channel = await self._get_log_channel(channel.guild)
        if not log_channel:
            return

        deleted_by = None
        if channel.guild.me.guild_permissions.view_audit_log:
            now = discord.utils.utcnow()
            try:
                async for entry in channel.guild.audit_logs(
                    limit=5, action=discord.AuditLogAction.channel_delete
                ):
                    if (
                        entry.target
                        and entry.target.id == channel.id
                        and (now - entry.created_at) <= timedelta(seconds=6)
                    ):
                        deleted_by = entry.user
                        break
            except (discord.Forbidden, discord.HTTPException):
                pass

        embed = discord.Embed(
            title="🗑️ Salon supprimé",
            description=f"Le salon **#{channel.name}** a été supprimé.",
            color=discord.Color.red(),
            timestamp=discord.utils.utcnow(),
        )
        if deleted_by:
            embed.add_field(
                name="Supprimé par", value=deleted_by.mention, inline=True
            )

        try:
            await log_channel.send(embed=embed)
        except discord.HTTPException:
            pass

    # -------------------------------------------------------------
    # 4. SALONS VOCAUX (Connexion, Déconnexion, Déplacement)
    # -------------------------------------------------------------

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ):
        log_channel = await self._get_log_channel(member.guild)
        if not log_channel:
            return

        if before.channel is None and after.channel is not None:
            embed = discord.Embed(
                title="🔊 Connexion Vocale",
                description=f"{member.mention} a rejoint le salon vocal {after.channel.mention}.",
                color=discord.Color.blue(),
                timestamp=discord.utils.utcnow(),
            )
            try:
                await log_channel.send(embed=embed)
            except discord.HTTPException:
                pass

        elif before.channel is not None and after.channel is None:
            embed = discord.Embed(
                title="🔇 Déconnexion Vocale",
                description=f"{member.mention} a quitté le salon vocal **{before.channel.name}**.",
                color=discord.Color.dark_grey(),
                timestamp=discord.utils.utcnow(),
            )
            try:
                await log_channel.send(embed=embed)
            except discord.HTTPException:
                pass

        elif (
            before.channel is not None
            and after.channel is not None
            and before.channel != after.channel
        ):
            embed = discord.Embed(
                title="🔀 Déplacement Vocal",
                description=f"{member.mention} s'est déplacé de {before.channel.mention} vers {after.channel.mention}.",
                color=discord.Color.gold(),
                timestamp=discord.utils.utcnow(),
            )
            try:
                await log_channel.send(embed=embed)
            except discord.HTTPException:
                pass

    # -------------------------------------------------------------
    # 5. RÔLES DU SERVEUR (Création, Suppression)
    # -------------------------------------------------------------

    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role):
        log_channel = await self._get_log_channel(role.guild)
        if not log_channel:
            return

        created_by = None
        if role.guild.me.guild_permissions.view_audit_log:
            now = discord.utils.utcnow()
            try:
                async for entry in role.guild.audit_logs(
                    limit=5, action=discord.AuditLogAction.role_create
                ):
                    if (
                        entry.target
                        and entry.target.id == role.id
                        and (now - entry.created_at) <= timedelta(seconds=6)
                    ):
                        created_by = entry.user
                        break
            except (discord.Forbidden, discord.HTTPException):
                pass

        embed = discord.Embed(
            title="🎭 Rôle créé",
            description=f"Le rôle {role.mention} (`{role.name}`) a été créé.",
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow(),
        )
        if created_by:
            embed.add_field(
                name="Créé par", value=created_by.mention, inline=True
            )

        try:
            await log_channel.send(embed=embed)
        except discord.HTTPException:
            pass

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role):
        log_channel = await self._get_log_channel(role.guild)
        if not log_channel:
            return

        deleted_by = None
        if role.guild.me.guild_permissions.view_audit_log:
            now = discord.utils.utcnow()
            try:
                async for entry in role.guild.audit_logs(
                    limit=5, action=discord.AuditLogAction.role_delete
                ):
                    if (
                        entry.target
                        and entry.target.id == role.id
                        and (now - entry.created_at) <= timedelta(seconds=6)
                    ):
                        deleted_by = entry.user
                        break
            except (discord.Forbidden, discord.HTTPException):
                pass

        embed = discord.Embed(
            title="🗑️ Rôle supprimé",
            description=f"Le rôle **{role.name}** a été supprimé.",
            color=discord.Color.red(),
            timestamp=discord.utils.utcnow(),
        )
        if deleted_by:
            embed.add_field(
                name="Supprimé par", value=deleted_by.mention, inline=True
            )

        try:
            await log_channel.send(embed=embed)
        except discord.HTTPException:
            pass


async def setup(bot):
    await bot.add_cog(LogsCog(bot))