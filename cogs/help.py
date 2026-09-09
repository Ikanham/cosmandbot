import discord
from discord import app_commands
from discord.ext import commands
from utils.permissions import can_manage_check


class HelpCog(commands.Cog, name="Help"):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(
        name="help",
        description="Affiche la liste complète des commandes disponibles.",
    )
    async def help_command(self, interaction: discord.Interaction):
        can_access_admin = await can_manage_check(interaction)

        embed = discord.Embed(
            title="📖 Aide du bot - Commandes",
            description="Voici la liste des commandes Slash disponibles selon vos permissions :",
            color=discord.Color.blurple(),
        )

        embed.add_field(
            name="🎂 Anniversaires",
            value=(
                "`/anniversaire liste` — Voir la liste des anniversaires à venir\n"
                "`/anniversaire definir [date] [membre]` — Enregistrer/modifier un anniversaire\n"
                "`/anniversaire supprimer [membre]` — Supprimer un anniversaire *(Modération)*"
            ),
            inline=False,
        )

        if can_access_admin:
            embed.add_field(
                name="📢 Annonces Bot",
                value=(
                    "`/annonce copier [salon] [message_id]` — Cloner un message avec ses médias vers un salon\n"
                    "*Clic droit sur un message* -> Applications -> **Publier en annonce**"
                ),
                inline=False,
            )

            embed.add_field(
                name="🎉 Sorties & Événements",
                value=(
                    "`/sortie creer` — Créer une nouvelle sortie avec salon et rôle dédiés\n"
                    "`/sortie modifier` — Modifier la sortie liée au salon actuel\n"
                    "`/sortie ajouter [membre] [#salon]` — Inscrire un membre\n"
                    "`/sortie retirer [membre]` — Retirer un membre de la sortie\n"
                    "`/sortie archiver` — Clôturer la sortie, supprimer le salon et le rôle"
                ),
                inline=False,
            )

            embed.add_field(
                name="🎭 Conventions Cosplay",
                value=(
                    "`/convention creer [#salon]` — Créer un panneau interactif avec sélection des jours et rôle automatique\n"
                    "`/convention archiver [id]` — Clôturer une convention et supprimer son rôle\n"
                    "`/convention liste` — Lister les conventions cosplay actives"
                ),
                inline=False,
            )

            embed.add_field(
                name="📅 Comptes à rebours",
                value=(
                    "`/rebours ajouter [date] [heure] [titre]` — Ajouter un compte à rebours\n"
                    "`/rebours liste` — Lister les rebours actifs\n"
                    "`/rebours supprimer [nom/id]` — Supprimer un compte à rebours"
                ),
                inline=False,
            )

            embed.add_field(
                name="⏰ Messages Planifiés",
                value=(
                    "`/planifier message [#salon] [date] [heure]` — Planifier un message unique\n"
                    "`/planifier liste` — Lister les messages en attente\n"
                    "`/planifier supprimer [id]` — Supprimer un message planifié"
                ),
                inline=False,
            )

            embed.add_field(
                name="🌞 Bonne journée",
                value=(
                    "`/bonnejournee ajouter [message]` — Ajouter une phrase de salutation\n"
                    "`/bonnejournee modifier [id]` — Modifier une phrase existante\n"
                    "`/bonnejournee supprimer [id]` — Supprimer une phrase par ID\n"
                    "`/bonnejournee liste` — Voir les phrases enregistrées\n"
                    "`/bonnejournee salon [#salon]` — Définir le salon d'envoi quotidien\n"
                    "`/bonnejournee heure [0-23]` — Définir l'heure d'envoi"
                ),
                inline=False,
            )

            embed.add_field(
                name="⚙️ Administration & Configuration",
                value=(
                    "`/config salon-accueil [#salon]` — Définir salon d'arrivée & départ\n"
                    "`/config salon-anniversaire [#salon]` — Salon d'annonce des anniversaires\n"
                    "`/config heure-anniversaire [0-23]` — Heure d'annonce des anniversaires\n"
                    "`/config salon-rebours [#salon]` — Salon des comptes à rebours\n"
                    "`/config heure-rebours [h] [m]` — Heure quotidienne des rebours\n"
                    "`/config salon-logs [#salon]` — Salon de journalisation des logs\n"
                    "`/config role-mod [@role]` — Définir le rôle modérateur du bot\n"
                    "`/config fuseau [zone]` — Fuseau horaire (ex: Europe/Paris)\n"
                    "`/config afficher` — Afficher tous les réglages actuels\n"
                    "`/purger nombre [1-100]` — Supprimer les X derniers messages\n"
                    "`/purger minutes [1-1440]` — Supprimer les messages récents par durée\n"
                    "`/hack [membre]` — Expulser un compte piraté et purger ses messages (10 min)"
                ),
                inline=False,
            )

        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(HelpCog(bot))