import discord
from discord.ext import commands
from discord.ui import View, Select
from typing import Optional

COMMAND_CATEGORIES = {
    "🌐 Général": {
        "description": "Commandes de base accessibles à tous.",
        "commands": {
            "d!help":     "Affiche cette aide. `d!help <commande>` pour le détail d'une commande.",
            "d!postuler": "Ouvre le menu de candidature pour rejoindre une division.",
            "d!profil":   "Affiche ton profil ou celui d'un autre membre. `d!profil @membre`",
            "d!divinfo":  "Affiche les infos d'une division. `d!divinfo 1`",
            "d!bliste":   "Liste les divisions que tu as bloquées.",
            "d!debloquer":"Débloque une division. `d!debloquer 1`",
            "d!quitter":  "Quitte ta division actuelle (cooldown de 3 jours).",
        },
    },
    "👑 Capitaine": {
        "description": "Commandes réservées aux capitaines de division.",
        "commands": {
            "d!inviter":  "Invite directement un membre dans ta division. `d!inviter @membre`",
            "d!config":   "Lance la configuration interactive de ta division.",
            "d!rank":     "Promeut un membre. `d!rank @membre 1` (Lieutenant) ou `2` (Vice-Capitaine).",
            "d!unrank":   "Retire le rang d'un membre. `d!unrank @membre`",
            "d!kick":     "Expulse un membre de ta division (cooldown 3 jours). `d!kick @membre`",
            "d!ban":      "Bannit définitivement un membre du système. `d!ban @membre`",
            "d!deban":    "Débannit un membre. `d!deban @membre`",
        },
    },
}

COMMAND_DETAILS = {
    "d!help":     "Affiche l'aide interactive. Avec `d!help <commande>`, affiche le détail complet de cette commande.",
    "d!postuler": "Lance le menu de candidature. Sélectionne ta division dans le menu déroulant. Un ticket privé est créé avec le staff.",
    "d!profil":   "Affiche ton profil (ou celui d'un autre en mentionnant `@membre`). Si c'est ton profil, des boutons d'édition apparaissent pour changer ta bio, couleur, PP et bannière.",
    "d!divinfo":  "Affiche les informations complètes d'une division : membres, règlement, bannière. Exemple : `d!divinfo 6`",
    "d!bliste":   "Affiche la liste des divisions dont tu bloques les invitations.",
    "d!debloquer":"Débloque une division pour recevoir de nouveau ses invitations. Exemple : `d!debloquer 1`",
    "d!quitter":  "Quitte proprement ta division avec confirmation. Un cooldown de 3 jours s'applique avant de pouvoir repostuler.",
    "d!inviter":  "**Capitaine** — Invite directement un membre. L'invitation apparaît dans le salon #entrants avec boutons Accepter/Refuser/Bloquer. Expire après 3 minutes.",
    "d!config":   "**Capitaine** — Configure ta division étape par étape dans le chat (nom, description, âge, règlement, images, couleur). Cooldown de 7 jours entre modifications.",
    "d!rank":     "**Capitaine** — Promeut un membre de ta division. `1` = Lieutenant, `2` = Vice-Capitaine. Cooldown de 10 jours par rang.",
    "d!unrank":   "**Capitaine** — Retire le rang actuel d'un membre de ta division.",
    "d!kick":     "**Capitaine** — Expulse un membre de ta division avec confirmation. Cooldown de 3 jours avant réintégration.",
    "d!ban":      "**Capitaine** — Bannit définitivement un membre de toutes les divisions jusqu'au débannissement.",
    "d!deban":    "**Capitaine** — Révoque le bannissement d'un membre.",
}


class HelpView(View):
    def __init__(self, category: str = "🌐 Général", mode: str = "Aperçu"):
        super().__init__(timeout=None)
        self.category = category
        self.mode = mode
        self.add_item(HelpCategorySelect(self))
        self.add_item(HelpModeSelect(self))

    def build_embed(self) -> discord.Embed:
        cat_data = COMMAND_CATEGORIES[self.category]
        embed = discord.Embed(
            title=f"📖 Aide — {self.category}",
            description=cat_data["description"],
            color=discord.Color.blurple(),
        )
        for cmd, text in cat_data["commands"].items():
            value = COMMAND_DETAILS.get(cmd, text) if self.mode == "Détails" else text
            embed.add_field(name=f"`{cmd}`", value=value, inline=False)
        embed.set_footer(text="Préfixe : d!  •  Utilise les menus ci-dessous pour naviguer")
        return embed


class HelpCategorySelect(Select):
    def __init__(self, help_view: HelpView):
        options = [
            discord.SelectOption(
                label=name,
                description=data["description"][:50],
                value=name,
                emoji=name.split()[0],
            )
            for name, data in COMMAND_CATEGORIES.items()
        ]
        super().__init__(placeholder="Choisis une catégorie…", min_values=1, max_values=1, options=options)
        self.help_view = help_view

    async def callback(self, interaction: discord.Interaction) -> None:
        self.help_view.category = self.values[0]
        await interaction.response.edit_message(embed=self.help_view.build_embed(), view=self.help_view)


class HelpModeSelect(Select):
    def __init__(self, help_view: HelpView):
        options = [
            discord.SelectOption(label="Aperçu", description="Résumé court de chaque commande", value="Aperçu"),
            discord.SelectOption(label="Détails", description="Description complète et exemples", value="Détails"),
        ]
        super().__init__(placeholder="Niveau de détail…", min_values=1, max_values=1, options=options)
        self.help_view = help_view

    async def callback(self, interaction: discord.Interaction) -> None:
        self.help_view.mode = self.values[0]
        await interaction.response.edit_message(embed=self.help_view.build_embed(), view=self.help_view)


class HelpCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.command(name="help", aliases=["aide", "h"])
    async def help_command(self, ctx: commands.Context, command_name: Optional[str] = None) -> None:
        """Affiche l'aide interactive ou le détail d'une commande."""
        if command_name:
            key = command_name if command_name.startswith("d!") else f"d!{command_name}"
            detail = COMMAND_DETAILS.get(key)
            if not detail:
                await ctx.reply(f"❌ Commande `{key}` inconnue. Utilise `d!help` pour voir toutes les commandes.", delete_after=8)
                return
            embed = discord.Embed(
                title=f"📖 Aide — `{key}`",
                description=detail,
                color=discord.Color.green(),
            )
            embed.add_field(name="Usage", value=f"`{key}`", inline=False)
            await ctx.reply(embed=embed)
            return

        view = HelpView()
        await ctx.reply(embed=view.build_embed(), view=view)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(HelpCog(bot))
