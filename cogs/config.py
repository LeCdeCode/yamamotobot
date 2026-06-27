"""
Config cog — entièrement sans modals.
La configuration se fait étape par étape en envoyant des messages dans le chat.
URLs d'images/GIFs supportés nativement (Discord CDN, Giphy, Tenor, Imgur, etc.).
"""

import asyncio
import re
from datetime import datetime
from typing import Optional

import discord
from discord.ext import commands
from discord.ui import View, Button

from .utils import (
    DIVISIONS, DIVISION_CAPTAIN_ROLE_ID,
    get_division_by_member, get_division_number,
    load_division_config, save_division_config,
    check_cooldown_config, set_cooldown_config,
    load_json, save_json, COOLDOWNS_FILE,
)

COOLDOWN_DAYS = 7

# Regex pour détecter les URLs d'image/GIF valides
IMAGE_URL_RE = re.compile(
    r"https?://\S+\.(png|jpg|jpeg|gif|webp)(\?[^\s]*)?"
    r"|https?://(?:media\.discordapp\.net|cdn\.discordapp\.com|i\.imgur\.com"
    r"|media\.giphy\.com|tenor\.com|c\.tenor\.com|i\.giphy\.com)\S+",
    re.IGNORECASE,
)

STEPS = [
    ("custom_name",  "📝 **Nom personnalisé**",   "Envoie le nom de ta division (ex: `Shinigami Corps`), ou `skip` pour garder le nom par défaut."),
    ("description",  "📄 **Description**",         "Envoie une description de ta division (max 500 caractères), ou `skip`."),
    ("min_age",      "📅 **Âge minimum**",          "Envoie l'âge minimum requis (ex: `13`), ou `skip` pour aucun."),
    ("rules",        "📋 **Règlement interne**",    "Envoie le règlement de ta division (max 1000 caractères), ou `skip`."),
    ("profile_url",  "🖼️ **Image de profil (PP)**", "Envoie un lien d'image/GIF ou attache directement une image, ou `skip`."),
    ("banner_url",   "🎨 **Bannière**",              "Envoie un lien d'image/GIF ou attache directement une image, ou `skip`."),
    ("role_color",   "🔴 **Couleur du rôle**",      "Envoie une couleur hex (ex: `FF5733`), ou `skip`."),
]


def _extract_image_url(message: discord.Message) -> Optional[str]:
    """Extrait une URL d'image depuis un message (pièce jointe ou URL dans le texte)."""
    if message.attachments:
        att = message.attachments[0]
        if att.content_type and att.content_type.startswith(("image/", "video/")):
            return att.url
        if IMAGE_URL_RE.search(att.url):
            return att.url
    if message.content:
        match = IMAGE_URL_RE.search(message.content)
        if match:
            return match.group(0)
    return None


def _config_embed(step_index: int, config: dict, division_name: str) -> discord.Embed:
    key, title, instructions = STEPS[step_index]
    embed = discord.Embed(
        title=f"⚙️ Configuration — {division_name}  ({step_index + 1}/{len(STEPS)})",
        description=f"**{title}**\n\n{instructions}",
        color=discord.Color.blurple(),
    )

    # Aperçu des valeurs déjà renseignées
    preview_lines = []
    labels = {
        "custom_name": "Nom",
        "description":  "Description",
        "min_age":      "Âge minimum",
        "rules":        "Règlement",
        "profile_url":  "Image profil",
        "banner_url":   "Bannière",
        "role_color":   "Couleur rôle",
    }
    for k, label in labels.items():
        val = config.get(k)
        if val:
            short = val if len(val) <= 60 else val[:57] + "…"
            preview_lines.append(f"✅ **{label}** : {short}")
        elif k == key:
            preview_lines.append(f"➡️ **{label}** : *en attente…*")
        else:
            preview_lines.append(f"⬜ **{label}** : *non configuré*")

    embed.add_field(name="Récapitulatif", value="\n".join(preview_lines), inline=False)
    embed.set_footer(text="Réponds dans ce salon • 'skip' pour passer • 'annuler' pour quitter")
    return embed


class ConfigNavView(View):
    """Boutons de navigation affichés pendant la config."""
    def __init__(self, session: "ConfigSession"):
        super().__init__(timeout=None)
        self.session = session

    @discord.ui.button(label="⏭️ Passer", style=discord.ButtonStyle.secondary)
    async def skip_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.session.captain.id:
            await interaction.response.send_message("❌ Seul le capitaine peut configurer.", ephemeral=True)
            return
        await interaction.response.defer()
        await self.session.next_step()

    @discord.ui.button(label="❌ Annuler", style=discord.ButtonStyle.danger)
    async def cancel_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.session.captain.id:
            await interaction.response.send_message("❌ Seul le capitaine peut annuler.", ephemeral=True)
            return
        await interaction.response.defer()
        await self.session.cancel()


class ConfigPreviewView(View):
    """Boutons affichés sur l'aperçu final."""
    def __init__(self, session: "ConfigSession"):
        super().__init__(timeout=None)
        self.session = session

    @discord.ui.button(label="✅ Confirmer & Sauvegarder", style=discord.ButtonStyle.success)
    async def confirm_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.session.captain.id:
            await interaction.response.send_message("❌ Seul le capitaine peut confirmer.", ephemeral=True)
            return
        await interaction.response.defer()
        await self.session.confirm()

    @discord.ui.button(label="✏️ Recommencer", style=discord.ButtonStyle.primary)
    async def restart_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.session.captain.id:
            await interaction.response.send_message("❌ Seul le capitaine peut modifier.", ephemeral=True)
            return
        await interaction.response.defer()
        self.session.step = 0
        await self.session.show_step()

    @discord.ui.button(label="❌ Annuler", style=discord.ButtonStyle.danger)
    async def cancel_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.session.captain.id:
            await interaction.response.send_message("❌ Seul le capitaine peut annuler.", ephemeral=True)
            return
        await interaction.response.defer()
        await self.session.cancel()


class ConfigSession:
    """Gère une session de configuration interactive pour un capitaine."""

    def __init__(
        self,
        cog: "ConfigManager",
        captain: discord.Member,
        division_name: str,
        channel: discord.TextChannel,
    ):
        self.cog = cog
        self.captain = captain
        self.division_name = division_name
        self.channel = channel
        self.step = 0
        self.config: dict = load_division_config(division_name) or {
            "custom_name": None,
            "description":  None,
            "min_age":      None,
            "rules":        None,
            "profile_url":  None,
            "banner_url":   None,
            "role_color":   None,
        }
        self.embed_message: Optional[discord.Message] = None
        self._waiting = True

    # ──────────────────────────────────────────────

    async def show_step(self) -> None:
        embed = _config_embed(self.step, self.config, self.division_name)
        nav_view = ConfigNavView(self)
        if self.embed_message:
            try:
                await self.embed_message.edit(embed=embed, view=nav_view)
                return
            except discord.HTTPException:
                pass
        self.embed_message = await self.channel.send(embed=embed, view=nav_view)

    async def handle_message(self, message: discord.Message) -> None:
        if not self._waiting:
            return

        content = message.content.strip()

        if content.lower() == "annuler":
            await self.cancel()
            return

        key = STEPS[self.step][0]

        if content.lower() == "skip":
            pass  # laisser la valeur existante / None

        elif key in ("profile_url", "banner_url"):
            url = _extract_image_url(message)
            if url:
                self.config[key] = url
            else:
                try:
                    await message.reply("⚠️ Aucune image détectée. Envoie un lien direct ou attache une image. (`skip` pour passer)", delete_after=8)
                except discord.HTTPException:
                    pass
                return  # ne pas avancer

        elif key == "role_color":
            hex_val = content.lstrip("#")
            if len(hex_val) == 6:
                try:
                    int(hex_val, 16)
                    self.config[key] = hex_val
                except ValueError:
                    await message.reply("⚠️ Couleur invalide. Format attendu : `FF5733`. (`skip` pour passer)", delete_after=8)
                    return
            else:
                await message.reply("⚠️ Couleur invalide. Format attendu : `FF5733`. (`skip` pour passer)", delete_after=8)
                return

        elif key == "min_age":
            if content:
                if content.isdigit():
                    self.config[key] = content
                else:
                    await message.reply("⚠️ Entre un nombre entier (ex: `13`). (`skip` pour passer)", delete_after=8)
                    return

        elif key in ("description", "rules"):
            max_len = 500 if key == "description" else 1000
            if len(content) > max_len:
                await message.reply(f"⚠️ Trop long ({len(content)} caractères). Maximum : {max_len}. (`skip` pour passer)", delete_after=8)
                return
            self.config[key] = content

        elif key == "custom_name":
            if len(content) > 100:
                await message.reply("⚠️ Trop long. Maximum : 100 caractères. (`skip` pour passer)", delete_after=8)
                return
            self.config[key] = content

        else:
            self.config[key] = content

        # Supprimer le message du capitaine pour garder propre
        try:
            await message.delete()
        except discord.HTTPException:
            pass

        await self.next_step()

    async def next_step(self) -> None:
        self.step += 1
        if self.step >= len(STEPS):
            await self.show_preview()
        else:
            await self.show_step()

    async def show_preview(self) -> None:
        embed = discord.Embed(
            title=f"👁️ Aperçu final — {self.division_name}",
            description=self.config.get("description") or "Aucune description.",
            color=discord.Color(int(self.config.get("role_color", "5865F2"), 16))
            if self.config.get("role_color") else discord.Color.blurple(),
        )

        name = self.config.get("custom_name") or f"Division {get_division_number(self.division_name)}"
        embed.title = f"👁️ Aperçu — {name}"

        if self.config.get("min_age"):
            embed.add_field(name="Âge minimum", value=f"{self.config['min_age']} ans", inline=True)
        if self.config.get("rules"):
            embed.add_field(name="Règlement", value=self.config["rules"][:1024], inline=False)
        if self.config.get("profile_url"):
            embed.set_thumbnail(url=self.config["profile_url"])
        if self.config.get("banner_url"):
            embed.set_image(url=self.config["banner_url"])

        embed.set_footer(text="Confirme ou recommence la configuration.")

        preview_view = ConfigPreviewView(self)
        if self.embed_message:
            try:
                await self.embed_message.edit(embed=embed, view=preview_view)
                return
            except discord.HTTPException:
                pass
        self.embed_message = await self.channel.send(embed=embed, view=preview_view)

    async def confirm(self) -> None:
        self._waiting = False
        save_division_config(self.division_name, self.config)
        set_cooldown_config(self.captain.id, self.division_name)

        # Appliquer la couleur au rôle si possible
        if self.config.get("role_color"):
            guild = self.captain.guild
            div_data = DIVISIONS.get(self.division_name)
            if div_data:
                role = guild.get_role(div_data["role_id"])
                if role:
                    try:
                        await role.edit(color=discord.Color(int(self.config["role_color"], 16)))
                    except (discord.Forbidden, ValueError):
                        pass

        embed = discord.Embed(
            title="✅ Configuration sauvegardée",
            description=(
                f"La configuration de **{self.division_name}** a été mise à jour avec succès !\n"
                f"⏱️ Prochaine modification possible dans {COOLDOWN_DAYS} jours."
            ),
            color=discord.Color.green(),
        )
        if self.embed_message:
            try:
                await self.embed_message.edit(embed=embed, view=None)
            except discord.HTTPException:
                pass

        self.cog.end_session(self.captain.id)

    async def cancel(self) -> None:
        self._waiting = False
        embed = discord.Embed(
            title="❌ Configuration annulée",
            description="La configuration n'a pas été modifiée.",
            color=discord.Color.red(),
        )
        if self.embed_message:
            try:
                await self.embed_message.edit(embed=embed, view=None)
            except discord.HTTPException:
                pass
        self.cog.end_session(self.captain.id)


# ──────────────────────────────────────────────
# Cog
# ──────────────────────────────────────────────

class ConfigManager(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._sessions: dict[int, ConfigSession] = {}

    def end_session(self, captain_id: int) -> None:
        self._sessions.pop(captain_id, None)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return
        session = self._sessions.get(message.author.id)
        if session and message.channel.id == session.channel.id:
            await session.handle_message(message)

    @commands.command(name="config")
    async def config_cmd(self, ctx: commands.Context) -> None:
        """Configure le profil de ta division. (Capitaine uniquement)"""
        if not ctx.guild:
            await ctx.reply("⚠️ Cette commande fonctionne uniquement sur le serveur.", delete_after=5)
            return

        if not ctx.author.get_role(DIVISION_CAPTAIN_ROLE_ID):
            await ctx.reply("❌ Seul un capitaine peut configurer sa division.", delete_after=5)
            return

        captain_division = get_division_by_member(ctx.author)
        if not captain_division:
            await ctx.reply("❌ Impossible de déterminer ta division.", delete_after=5)
            return

        division_name, _ = captain_division

        cooldown_until = check_cooldown_config(ctx.author.id, division_name, COOLDOWN_DAYS)
        if cooldown_until:
            remaining = cooldown_until - datetime.now()
            hours = int(remaining.total_seconds() // 3600)
            minutes = int((remaining.total_seconds() % 3600) // 60)
            await ctx.reply(
                f"⏳ Tu pourras modifier la config dans **{hours}h {minutes}m**.",
                delete_after=8,
            )
            return

        if ctx.author.id in self._sessions:
            await ctx.reply("⚠️ Tu as déjà une session de configuration en cours.", delete_after=5)
            return

        try:
            await ctx.message.delete()
        except discord.HTTPException:
            pass

        session = ConfigSession(self, ctx.author, division_name, ctx.channel)
        self._sessions[ctx.author.id] = session
        await session.show_step()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ConfigManager(bot))
