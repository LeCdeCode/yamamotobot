"""
Profile cog — profil membres et info divisions.
Modification de PP/bannière via URL ou pièce jointe dans le chat (plus de modals cassés).
"""

import re
from datetime import datetime
from typing import Optional

import discord
from discord.ext import commands
from discord.ui import View, Button

from .utils import (
    DIVISIONS, PROFILES_FILE, DIVISION_CAPTAIN_ROLE_ID, VICE_CAPTAIN_ROLE_ID, LIEUTENANT_ROLE_ID,
    load_json, save_json, MEMBERS_FILE,
    get_division_by_member, get_member_rank, get_member_join_date, get_rank_holder,
    get_division_captain, count_division_members,
)

IMAGE_URL_RE = re.compile(
    r"https?://\S+\.(png|jpg|jpeg|gif|webp)(\?[^\s]*)?"
    r"|https?://(?:media\.discordapp\.net|cdn\.discordapp\.com|i\.imgur\.com"
    r"|media\.giphy\.com|tenor\.com|c\.tenor\.com|i\.giphy\.com)\S+",
    re.IGNORECASE,
)

DIVISION_PROFILES_FILE = __import__("pathlib").Path(str(PROFILES_FILE).replace("member_profiles", "division_profiles"))


def _default_profile(user: discord.User | discord.Member) -> dict:
    return {
        "member_id":     user.id,
        "member_name":   user.name,
        "profile_color": "5865F2",
        "bio":           "",
        "profile_picture": None,
        "banner":        None,
        "private":       False,
        "created_at":    datetime.now().isoformat(),
    }


def _profile_embed(target: discord.Member, profile: dict) -> discord.Embed:
    try:
        color = discord.Color(int(profile.get("profile_color", "5865F2"), 16))
    except (ValueError, TypeError):
        color = discord.Color.blurple()

    member_division = get_division_by_member(target)
    division_name   = member_division[0] if member_division else "Aucune"
    rank            = get_member_rank(target.id, division_name) if member_division else None
    join_date       = get_member_join_date(target.id, division_name) if member_division else None

    embed = discord.Embed(
        title=target.display_name,
        description=profile.get("bio") or "*Aucune biographie.*",
        color=color,
    )
    embed.set_thumbnail(url=profile.get("profile_picture") or target.display_avatar.url)

    if profile.get("banner"):
        embed.set_image(url=profile["banner"])

    embed.add_field(name="🏷️ Division", value=division_name, inline=True)

    grade = "Membre"
    grade_role: Optional[discord.Role] = None
    if member_division:
        grade_role_map = [
            (DIVISION_CAPTAIN_ROLE_ID, "Capitaine"),
            (VICE_CAPTAIN_ROLE_ID, "Vice-capitaine"),
            (LIEUTENANT_ROLE_ID, "Lieutenant"),
        ]
        for role_id, label in grade_role_map:
            if any(role.id == role_id for role in target.roles):
                grade = label
                grade_role = target.guild.get_role(role_id)
                break
    embed.add_field(name="🎖️ Grade", value=grade, inline=True)
    if grade_role:
        embed.add_field(name="🔰 Role", value=grade_role.mention, inline=True)

    if rank:
        embed.add_field(name="⚔️ Rang", value=rank, inline=True)
    if join_date:
        try:
            join_dt = datetime.fromisoformat(join_date)
            days = (datetime.now() - join_dt).days
            embed.add_field(name="📅 Membre depuis", value=f"{days} jour{'s' if days != 1 else ''}", inline=True)
        except (ValueError, TypeError):
            pass

    embed.set_footer(text=f"Profil de {target.name} • {'🔒 Privé' if profile.get('private') else '🔓 Public'}")
    return embed


# ──────────────────────────────────────────────
# Vue gestion du profil
# ──────────────────────────────────────────────

class ProfileEditView(View):
    """Boutons pour modifier son propre profil."""

    def __init__(self, cog: "ProfileManager", member: discord.Member):
        super().__init__(timeout=300)
        self.cog = cog
        self.member = member
    @discord.ui.button(label="🖼️ Changer PP", style=discord.ButtonStyle.primary, row=0)
    async def edit_pp_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.member.id:
            await interaction.response.send_message("❌ C'est pas ton profil.", ephemeral=True)
            return
        await interaction.response.defer()
        embed = discord.Embed(
            title="🖼️ Changer l'image de profil",
            description="Envoie un lien d'image/GIF ou attache directement une image.\nEnvoie `none` pour supprimer. Tu as 2 minutes.",
            color=discord.Color.blurple(),
        )
        prompt = await interaction.channel.send(embed=embed)
        self.cog.start_edit_session(self.member.id, "profile_picture", interaction.channel.id, prompt)

    @discord.ui.button(label="🏳️ Changer bannière", style=discord.ButtonStyle.primary, row=0)
    async def edit_banner_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.member.id:
            await interaction.response.send_message("❌ C'est pas ton profil.", ephemeral=True)
            return
        await interaction.response.defer()
        embed = discord.Embed(
            title="🏳️ Changer la bannière",
            description="Envoie un lien d'image/GIF ou attache directement une image.\nEnvoie `none` pour supprimer. Tu as 2 minutes.",
            color=discord.Color.blurple(),
        )
        prompt = await interaction.channel.send(embed=embed)
        self.cog.start_edit_session(self.member.id, "banner", interaction.channel.id, prompt)

    @discord.ui.button(label="✏️ Changer bio/couleur", style=discord.ButtonStyle.primary, row=1)
    async def edit_bio_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.member.id:
            await interaction.response.send_message("❌ C'est pas ton profil.", ephemeral=True)
            return
        await interaction.response.defer()
        embed = discord.Embed(
            title="✏️ Modifier bio & couleur",
            description=(
                "Envoie un message dans ce format :\n\n"
                "```\nbio: Ton texte ici (max 200 caractères)\n"
                "couleur: FF5733\n```\n"
                "Tu peux n'envoyer qu'un des deux. Réponds dans ce salon dans les 2 minutes."
            ),
            color=discord.Color.blurple(),
        )
        prompt = await interaction.channel.send(embed=embed)
        self.cog.start_edit_session(self.member.id, "bio_color", interaction.channel.id, prompt)
    @discord.ui.button(label="🔐 Basculer privé/public", style=discord.ButtonStyle.secondary, row=1)
    async def toggle_private_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.member.id:
            await interaction.response.send_message("❌ C'est pas ton profil.", ephemeral=True)
            return
        await interaction.response.defer()
        profiles = load_json(PROFILES_FILE)
        key = str(self.member.id)
        if key not in profiles:
            profiles[key] = _default_profile(self.member)
        profiles[key]["private"] = not profiles[key].get("private", False)
        save_json(PROFILES_FILE, profiles)
        status = "🔒 Privé" if profiles[key]["private"] else "🔓 Public"
        await interaction.channel.send(f"✅ Profil maintenant **{status}**.", delete_after=5)
        # Update live profile message if present
        try:
            await self.cog._update_profile_message(self.member.id)
        except Exception:
            pass


# ──────────────────────────────────────────────
# Cog
# ──────────────────────────────────────────────

class ProfileManager(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # { member_id: {"field": str, "channel_id": int, "prompt": Message} }
        self._edit_sessions: dict[int, dict] = {}
        # track last profile message sent per member for live updates
        self._profile_messages: dict[int, dict] = {}

    def start_edit_session(self, member_id: int, field: str, channel_id: int, prompt: discord.Message) -> None:
        self._edit_sessions[member_id] = {"field": field, "channel_id": channel_id, "prompt": prompt}

    def end_edit_session(self, member_id: int) -> None:
        self._edit_sessions.pop(member_id, None)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return
        session = self._edit_sessions.get(message.author.id)
        if not session or message.channel.id != session["channel_id"]:
            return

        field   = session["field"]
        prompt  = session["prompt"]
        content = message.content.strip()

        profiles = load_json(PROFILES_FILE)
        key = str(message.author.id)
        if key not in profiles:
            profiles[key] = _default_profile(message.author)

        try:
            await message.delete()
        except discord.HTTPException:
            pass

        if field in ("profile_picture", "banner"):
            if content.lower() == "none":
                profiles[key][field] = None
                save_json(PROFILES_FILE, profiles)
                await prompt.delete()
                self.end_edit_session(message.author.id)
                await message.channel.send(f"✅ {field.replace('_', ' ').title()} supprimée.", delete_after=5)
                return

            url = None
            if message.attachments:
                att = message.attachments[0]
                url = att.url
            elif IMAGE_URL_RE.search(content):
                url = IMAGE_URL_RE.search(content).group(0)

            if not url:
                await message.channel.send("⚠️ Aucune image détectée. Réessaie.", delete_after=6)
                return

            profiles[key][field] = url
            save_json(PROFILES_FILE, profiles)
            await prompt.delete()
            self.end_edit_session(message.author.id)
            await message.channel.send("✅ Image mise à jour !", delete_after=5)
            try:
                await self._update_profile_message(message.author.id)
            except Exception:
                pass

        elif field == "bio_color":
            updated = []
            for line in content.splitlines():
                line = line.strip()
                if line.lower().startswith("bio:"):
                    bio = line[4:].strip()[:200]
                    profiles[key]["bio"] = bio
                    updated.append("bio")
                elif line.lower().startswith("couleur:"):
                    hex_val = line[8:].strip().lstrip("#")
                    if len(hex_val) == 6:
                        try:
                            int(hex_val, 16)
                            profiles[key]["profile_color"] = hex_val
                            updated.append("couleur")
                        except ValueError:
                            pass

            if updated:
                save_json(PROFILES_FILE, profiles)
                await prompt.delete()
                self.end_edit_session(message.author.id)
                await message.channel.send(f"✅ Mis à jour : {', '.join(updated)}.", delete_after=5)
                try:
                    await self._update_profile_message(message.author.id)
                except Exception:
                    pass
            else:
                await message.channel.send("⚠️ Format non reconnu. Utilise `bio: ...` et/ou `couleur: RRGGBB`.", delete_after=8)

    # ──────────────────────────────────────────────
    # d!profil
    # ──────────────────────────────────────────────

    @commands.command(name="profil")
    async def profil(self, ctx: commands.Context, member: Optional[discord.Member] = None) -> None:
        """Affiche le profil d'un membre (toi-même si aucun argument). Ne propose pas d'édition — utilise `d!cprofil` pour modifier."""
        if not ctx.guild:
            await ctx.reply("⚠️ Cette commande fonctionne uniquement sur le serveur.", delete_after=5)
            return

        target = member or ctx.author

        profiles = load_json(PROFILES_FILE)
        key = str(target.id)
        if key not in profiles:
            profiles[key] = _default_profile(target)
            save_json(PROFILES_FILE, profiles)

        profile = profiles[key]

        if profile.get("private") and target.id != ctx.author.id:
            await ctx.reply("🔒 Ce profil est privé.", delete_after=5)
            return

        embed = _profile_embed(target, profile)
        # d!profil affiche seulement le profil. Pour éditer, utiliser d!cprofil.
        await ctx.send(embed=embed)

    @commands.command(name="cprofil")
    async def cprofil(self, ctx: commands.Context) -> None:
        """Ouvre l'interface d'édition de ton profil (boutons)."""
        if not ctx.guild:
            await ctx.reply("⚠️ Cette commande fonctionne uniquement sur le serveur.", delete_after=5)
            return

        target = ctx.author
        profiles = load_json(PROFILES_FILE)
        key = str(target.id)
        if key not in profiles:
            profiles[key] = _default_profile(target)
            save_json(PROFILES_FILE, profiles)

        profile = profiles[key]
        embed = _profile_embed(target, profile)
        view = ProfileEditView(self, target)
        msg = await ctx.send(embed=embed, view=view)
        # store message for live updates
        self._profile_messages[target.id] = {"channel_id": msg.channel.id, "message_id": msg.id}

    # ──────────────────────────────────────────────
    # d!divinfo
    # ──────────────────────────────────────────────

    @commands.command(name="divinfo")
    async def divinfo(self, ctx: commands.Context, division_num: Optional[str] = None) -> None:
        """Affiche les informations d'une division. Exemple : `d!divinfo 1`"""
        if not ctx.guild:
            await ctx.reply("⚠️ Cette commande fonctionne uniquement sur le serveur.", delete_after=5)
            return

        # determine division name
        if division_num is None:
            member_div = get_division_by_member(ctx.author)
            if not member_div:
                await ctx.reply("❗ Tu n'appartiens à aucune division. Précise une division : `d!divinfo 1`.", delete_after=8)
                return
            division_name = member_div[0]
        else:
            # accept either a number or full name
            if division_num.isdigit():
                division_name = f"Division {division_num}"
            elif division_num.lower().startswith("division"):
                division_name = division_num.title()
            else:
                division_name = f"Division {division_num}"

        if division_name not in DIVISIONS:
            available = ", ".join(DIVISIONS.keys())
            await ctx.reply(f"❌ Division introuvable. Disponibles : {available}", delete_after=8)
            return

        division_data = DIVISIONS[division_name]
        role = ctx.guild.get_role(division_data["role_id"])
        if not role:
            await ctx.reply("❌ Impossible de charger le rôle de la division.", delete_after=5)
            return

        # Charger le profil de division
        from .utils import load_division_config
        config = load_division_config(division_name)

        name = config.get("custom_name") or division_name
        desc = config.get("description") or "Aucune description."

        color_hex = config.get("role_color")
        try:
            color = discord.Color(int(color_hex, 16)) if color_hex else discord.Color.blurple()
        except (ValueError, TypeError):
            color = discord.Color.blurple()

        embed = discord.Embed(title=name, description=desc, color=color)

        if config.get("banner_url"):
            embed.set_image(url=config["banner_url"])
        if config.get("profile_url"):
            embed.set_thumbnail(url=config["profile_url"])

        member_count = len(role.members)
        embed.add_field(name="👥 Membres", value=f"{member_count}/8", inline=True)
        embed.add_field(name="🏷️ Rôle", value=role.mention, inline=True)

        # load members mapping to find ranks
        from .utils import load_division_config
        members_map = load_json(MEMBERS_FILE)

        # captain
        captain = get_division_captain(ctx.guild, division_name)
        captain_mention = captain.mention if captain else "Aucun"

        # vice & lieutenant via helper
        lieutenant = get_rank_holder(ctx.guild, division_name, 1)
        vice = get_rank_holder(ctx.guild, division_name, 2)

        embed.add_field(name="👑 Capitaine", value=captain_mention, inline=True)
        embed.add_field(name="🤝 Vice-capitaine", value=(vice.mention if vice else "Aucun"), inline=True)
        embed.add_field(name="🛡️ Lieutenant", value=(lieutenant.mention if lieutenant else "Aucun"), inline=True)

        if config.get("min_age"):
            embed.add_field(name="📅 Âge minimum", value=f"{config['min_age']} ans", inline=True)

        if config.get("rules"):
            embed.add_field(name="📋 Règlement", value=config["rules"][:1024], inline=False)

        if role.members:
            members_lines = "\n".join(f"• {m.display_name} ({m.mention})" for m in role.members[:10])
            if len(role.members) > 10:
                members_lines += f"\n*… et {len(role.members) - 10} de plus*"
            embed.add_field(name="🪪 Membres", value=members_lines, inline=False)

        embed.set_footer(text=division_name)
        await ctx.send(embed=embed)

    # helper for live edits
    async def _update_profile_message(self, member_id: int) -> None:
        data = getattr(self, "_profile_messages", None)
        if not data:
            return
        info = data.get(member_id)
        if not info:
            return
        channel = self.bot.get_channel(info["channel_id"]) if isinstance(info, dict) else None
        if not channel:
            return
        try:
            msg = await channel.fetch_message(info["message_id"])
        except Exception:
            return
        # build embed
        guild = channel.guild
        member = guild.get_member(member_id)
        if not member:
            return
        profiles = load_json(PROFILES_FILE)
        profile = profiles.get(str(member_id)) or _default_profile(member)
        embed = _profile_embed(member, profile)
        try:
            await msg.edit(embed=embed)
        except Exception:
            return


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ProfileManager(bot))
