import asyncio
import io
from datetime import datetime
from typing import Optional

import discord
from discord.ext import commands
from discord.ui import View, Button, Select

from .utils import (
    APPLICATIONS_FILE, DIVISIONS,
    DIVISION_CAPTAIN_ROLE_ID, VICE_CAPTAIN_ROLE_ID,
    load_json, save_json,
    get_division_by_member, count_division_members, get_division_number,
    is_member_banned, can_rejoin_after_kick,
    can_rejoin_after_leave, add_member_to_division, send_join_announcement,
)


# ──────────────────────────────────────────────
# Ticket View (persistante)
# ──────────────────────────────────────────────

class ApplicationTicketView(View):
    """Boutons Accepter / Refuser / Fermer dans le ticket. Persistants après reboot."""

    def __init__(
        self,
        app_key: str,
        member_id: int,
        division_name: str,
        captain_id: int,
        vice_id: Optional[int],
        ticket_channel_id: Optional[int] = None,
    ):
        super().__init__(timeout=None)
        self.app_key = app_key
        self.member_id = member_id
        self.division_name = division_name
        self.captain_id = captain_id
        self.vice_id = vice_id
        self.ticket_channel_id = ticket_channel_id

        accept_btn = Button(
            label="Accepter", style=discord.ButtonStyle.success, emoji="✅",
            custom_id=f"app_accept_{app_key}",
        )
        refuse_btn = Button(
            label="Refuser", style=discord.ButtonStyle.danger, emoji="❌",
            custom_id=f"app_refuse_{app_key}",
        )
        close_btn = Button(
            label="Fermer le ticket", style=discord.ButtonStyle.secondary, emoji="🔐",
            custom_id=f"app_close_{app_key}",
        )
        accept_btn.callback = self._accept_callback
        refuse_btn.callback = self._refuse_callback
        close_btn.callback  = self._close_callback
        self.add_item(accept_btn)
        self.add_item(refuse_btn)
        self.add_item(close_btn)

    # ── helpers ──

    def _load_app(self) -> dict:
        return load_json(APPLICATIONS_FILE).get(self.app_key, {})

    def _save_app(self, app: dict) -> None:
        apps = load_json(APPLICATIONS_FILE)
        apps[self.app_key] = app
        save_json(APPLICATIONS_FILE, apps)

    def _is_authorized(self, user_id: int, for_close: bool = False) -> bool:
        if user_id == self.captain_id:
            return True
        if self.vice_id and user_id == self.vice_id:
            return True
        if for_close and user_id == self.member_id:
            return True
        return False

    async def _disable_buttons(self, message: discord.Message) -> None:
        for item in self.children:
            item.disabled = True
        try:
            await message.edit(view=self)
        except discord.HTTPException:
            pass

    async def _send_transcript_and_delete(
        self, channel: discord.TextChannel, member_user: Optional[discord.User]
    ) -> None:
        app = self._load_app()
        lines = [
            "=== Transcript du ticket de candidature ===",
            f"Candidat : {self.member_id}",
            f"Division  : {self.division_name}",
            f"Créé le   : {app.get('created_at', '?')}",
            f"Statut    : {app.get('status', '?')}",
            "--- Messages ---",
        ]
        for msg in app.get("messages", []):
            content = msg.get("content", "")
            attachments = msg.get("attachments", [])
            line = f"[{msg.get('timestamp')}] <{msg.get('author_id')}>: {content}"
            if attachments:
                line += " | " + ", ".join(attachments)
            lines.append(line)

        transcript_bytes = "\n".join(lines).encode()
        filename = f"ticket_{self.member_id}_{self.division_name}.txt"

        async def _send_file(user: discord.User | discord.Member):
            try:
                await user.send(file=discord.File(fp=io.BytesIO(transcript_bytes), filename=filename))
            except discord.Forbidden:
                pass

        if member_user:
            await _send_file(member_user)

        try:
            if channel and channel.guild:
                captain = channel.guild.get_member(self.captain_id)
                if captain:
                    await _send_file(captain)
        except Exception:
            pass

        await asyncio.sleep(3)
        try:
            await channel.delete(reason="Ticket terminé")
        except Exception:
            pass

    # ── callbacks ──

    async def _accept_callback(self, interaction: discord.Interaction) -> None:
        if not self._is_authorized(interaction.user.id):
            await interaction.response.send_message("❌ Tu n'as pas la permission d'accepter.", ephemeral=True)
            return

        is_captain = interaction.user.id == self.captain_id

        # Vice-capitaine → recommandation seulement
        if not is_captain:
            await interaction.response.defer()
            embed = discord.Embed(
                title="✅ Recommandation positive — Vice-Capitaine",
                description=f"{interaction.user.mention} recommande d'accepter <@{self.member_id}>.",
                color=discord.Color.blue(),
            )
            channel = interaction.guild.get_channel(self.ticket_channel_id)
            if channel:
                await channel.send(embed=embed)
            app = self._load_app()
            app.setdefault("messages", []).append({
                "timestamp": datetime.now().isoformat(),
                "author_id": interaction.user.id,
                "content": f"[Recommandation ACCEPT par vice-cap {interaction.user.id}]",
            })
            self._save_app(app)
            return

        # Capitaine → acceptation finale
        await interaction.response.defer()
        division_data = DIVISIONS.get(self.division_name)
        if not division_data:
            await interaction.followup.send("❌ Division introuvable.", ephemeral=True)
            return

        role = interaction.guild.get_role(division_data["role_id"]) if interaction.guild else None
        if not role:
            await interaction.followup.send("❌ Rôle de division introuvable.", ephemeral=True)
            return

        member = interaction.guild.get_member(self.member_id)
        channel = interaction.guild.get_channel(self.ticket_channel_id)

        try:
            if member:
                await member.add_roles(role, reason=f"Candidature acceptée — {self.division_name}")
                prefix = f"[Div {get_division_number(self.division_name)}] "
                base = member.nick or member.name
                if not base.startswith(prefix):
                    new_nick = prefix + base
                    if len(new_nick) > 32:
                        new_nick = prefix + base[:32 - len(prefix)]
                    try:
                        await member.edit(nick=new_nick)
                    except discord.Forbidden:
                        pass
            add_member_to_division(self.member_id, self.division_name)
            if member:
                await send_join_announcement(interaction.guild, member, self.division_name)
        except discord.Forbidden:
            await interaction.followup.send("❌ Impossible d'ajouter le rôle.", ephemeral=True)
            return

        app = self._load_app()
        app["status"] = "accepted"
        app.setdefault("messages", []).append({
            "timestamp": datetime.now().isoformat(),
            "author_id": interaction.user.id,
            "content": "Candidature acceptée par capitaine",
        })
        self._save_app(app)

        if channel:
            embed = discord.Embed(
                title="🎉 Candidature acceptée",
                description=f"<@{self.member_id}> a été accepté(e) dans **{self.division_name}** !",
                color=discord.Color.green(),
            )
            await channel.send(embed=embed)

        if member:
            try:
                await member.send(f"✅ Ta candidature pour **{self.division_name}** a été acceptée !")
            except discord.Forbidden:
                pass

        await self._disable_buttons(interaction.message)
        if channel:
            await self._send_transcript_and_delete(channel, member)

    async def _refuse_callback(self, interaction: discord.Interaction) -> None:
        if not self._is_authorized(interaction.user.id):
            await interaction.response.send_message("❌ Tu n'as pas la permission de refuser.", ephemeral=True)
            return

        is_captain = interaction.user.id == self.captain_id

        if not is_captain:
            await interaction.response.defer()
            embed = discord.Embed(
                title="❌ Recommandation négative — Vice-Capitaine",
                description=f"{interaction.user.mention} recommande de refuser <@{self.member_id}>.",
                color=discord.Color.orange(),
            )
            channel = interaction.guild.get_channel(self.ticket_channel_id)
            if channel:
                await channel.send(embed=embed)
            app = self._load_app()
            app.setdefault("messages", []).append({
                "timestamp": datetime.now().isoformat(),
                "author_id": interaction.user.id,
                "content": f"[Recommandation REFUS par vice-cap {interaction.user.id}]",
            })
            self._save_app(app)
            return

        await interaction.response.defer()
        channel = interaction.guild.get_channel(self.ticket_channel_id)
        member = interaction.guild.get_member(self.member_id)

        app = self._load_app()
        app["status"] = "refused"
        app.setdefault("messages", []).append({
            "timestamp": datetime.now().isoformat(),
            "author_id": interaction.user.id,
            "content": "Candidature refusée par capitaine",
        })
        self._save_app(app)

        if channel:
            embed = discord.Embed(
                title="❌ Candidature refusée",
                description=f"La candidature de <@{self.member_id}> pour **{self.division_name}** a été refusée.",
                color=discord.Color.red(),
            )
            await channel.send(embed=embed)

        if member:
            try:
                await member.send(f"❌ Ta candidature pour **{self.division_name}** a été refusée.")
            except discord.Forbidden:
                pass

        await self._disable_buttons(interaction.message)
        if channel:
            await self._send_transcript_and_delete(channel, member)

    async def _close_callback(self, interaction: discord.Interaction) -> None:
        if not self._is_authorized(interaction.user.id, for_close=True):
            await interaction.response.send_message("❌ Seul le capitaine ou le candidat peut fermer ce ticket.", ephemeral=True)
            return

        await interaction.response.defer()
        channel = interaction.guild.get_channel(self.ticket_channel_id)
        member = interaction.guild.get_member(self.member_id)

        app = self._load_app()
        app.setdefault("messages", []).append({
            "timestamp": datetime.now().isoformat(),
            "author_id": interaction.user.id,
            "content": "Ticket fermé manuellement",
        })
        self._save_app(app)

        if channel:
            embed = discord.Embed(
                title="🔐 Ticket fermé",
                description=f"Ce ticket a été fermé par {interaction.user.mention}.",
                color=discord.Color.greyple(),
            )
            await channel.send(embed=embed)

        await self._disable_buttons(interaction.message)
        if channel:
            await self._send_transcript_and_delete(channel, member)


# ──────────────────────────────────────────────
# Sélection de division
# ──────────────────────────────────────────────

class DivisionSelectView(View):
    def __init__(self, member: discord.Member, bot: commands.Bot):
        super().__init__(timeout=180)
        self.member = member
        self.bot = bot

        select = Select(
            placeholder="Choisis la division où tu veux postuler…",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(label=name, value=name, description=f"Postuler à la {name}")
                for name in DIVISIONS
            ],
        )
        select.callback = self._on_select
        self.add_item(select)

    async def _on_select(self, interaction: discord.Interaction) -> None:
        division_name: str = interaction.data["values"][0]

        # Vérifications
        if is_member_banned(self.member.id):
            await interaction.response.send_message("❌ Tu es banni(e) et ne peux pas postuler.", ephemeral=True)
            return

        if not can_rejoin_after_kick(self.member.id, division_name):
            await interaction.response.send_message("⏳ Tu dois attendre 3 jours après une expulsion avant de repostuler.", ephemeral=True)
            return

        if not can_rejoin_after_leave(self.member.id):
            await interaction.response.send_message("⏳ Tu dois attendre 3 jours après avoir quitté une division avant de repostuler.", ephemeral=True)
            return

        if count_division_members(interaction.guild, division_name) >= 8:
            await interaction.response.send_message(f"❌ **{division_name}** est complète (8/8).", ephemeral=True)
            return

        if get_division_by_member(self.member):
            await interaction.response.send_message("❌ Quitte d'abord ta division actuelle avant de postuler (`d!quitter`).", ephemeral=True)
            return

        await interaction.response.defer()

        guild = interaction.guild
        division_data = DIVISIONS[division_name]

        # Trouver capitaine & vice
        captain_role = guild.get_role(DIVISION_CAPTAIN_ROLE_ID)
        vice_role    = guild.get_role(VICE_CAPTAIN_ROLE_ID)
        captains     = [m for m in guild.members if captain_role in m.roles] if captain_role else []
        vice_captains= [m for m in guild.members if vice_role in m.roles] if vice_role else []

        captain      = captains[0] if captains else None
        vice_captain = vice_captains[0] if vice_captains else None

        if not captain:
            await interaction.followup.send("❌ Aucun capitaine trouvé.", ephemeral=True)
            return

        # Créer le channel ticket
        category = guild.get_channel(division_data["channels"].get("category"))
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            guild.me:           discord.PermissionOverwrite(view_channel=True, manage_channels=True, manage_messages=True),
            self.member:        discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            captain:            discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, manage_messages=True),
        }
        if vice_captain:
            overwrites[vice_captain] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)

        channel_name = f"candidature-{self.member.name.lower().replace(' ', '-')}"[:80]
        ticket_channel = await guild.create_text_channel(
            channel_name,
            category=category,
            overwrites=overwrites,
            reason=f"Ticket candidature {self.member.name} — {division_name}",
        )

        # Créer l'entrée
        created_at = datetime.now().isoformat()
        app_key = f"{self.member.id}_{division_name}_{created_at}"
        app_entry = {
            "app_key": app_key,
            "member_id": self.member.id,
            "division": division_name,
            "status": "pending",
            "messages": [],
            "created_at": created_at,
            "channel_id": ticket_channel.id,
            "message_id": None,
            "captain_id": captain.id,
            "vice_id": vice_captain.id if vice_captain else None,
        }
        apps = load_json(APPLICATIONS_FILE)
        apps[app_key] = app_entry
        save_json(APPLICATIONS_FILE, apps)

        view = ApplicationTicketView(
            app_key, self.member.id, division_name,
            captain.id, vice_captain.id if vice_captain else None,
            ticket_channel.id,
        )

        embed = discord.Embed(
            title=f"📋 Candidature — {division_name}",
            description=(
                f"Bienvenue {self.member.mention} !\n\n"
                "Ta candidature est en cours d'examen par le staff.\n"
                "Présente-toi et réponds aux questions du capitaine ci-dessous."
            ),
            color=discord.Color.blurple(),
        )
        embed.add_field(name="📌 Division", value=division_name, inline=True)
        embed.add_field(name="👤 Candidat", value=self.member.mention, inline=True)
        embed.add_field(name="👑 Capitaine", value=captain.mention, inline=True)
        embed.set_thumbnail(url=self.member.display_avatar.url)
        embed.set_footer(text="Le capitaine peut accepter, refuser ou fermer ce ticket.")

        welcome_msg = await ticket_channel.send(
            content=f"{self.member.mention} {captain.mention}" + (f" {vice_captain.mention}" if vice_captain else ""),
            embed=embed,
            view=view,
        )

        # Sauvegarder l'ID du message pour restaurer la view après reboot
        apps = load_json(APPLICATIONS_FILE)
        if app_key in apps:
            apps[app_key]["message_id"] = welcome_msg.id
            save_json(APPLICATIONS_FILE, apps)

        try:
            await welcome_msg.pin(reason="Message principal du ticket")
            # Supprimer la notif de pin
            async for msg in ticket_channel.history(limit=5):
                if msg.type == discord.MessageType.pins_add:
                    await msg.delete()
                    break
        except discord.HTTPException:
            pass

        # Enregistrer la vue persistante
        try:
            self.bot.add_view(view, message_id=welcome_msg.id)
        except Exception:
            pass

        try:
            await self.member.send(f"✅ Ton ticket pour **{division_name}** est ouvert : {ticket_channel.mention}")
        except discord.Forbidden:
            pass

        await interaction.followup.send(f"✅ Candidature créée ! {ticket_channel.mention}", ephemeral=True)


# ──────────────────────────────────────────────
# Cog
# ──────────────────────────────────────────────

class RecruitmentManager(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._restore_views()

    def _restore_views(self) -> None:
        """Restaure les vues persistantes des tickets ouverts après un reboot."""
        try:
            apps = load_json(APPLICATIONS_FILE)
            for app_key, app in apps.items():
                msg_id = app.get("message_id")
                if msg_id and app.get("status") == "pending":
                    view = ApplicationTicketView(
                        app_key,
                        app.get("member_id"),
                        app.get("division"),
                        app.get("captain_id"),
                        app.get("vice_id"),
                        app.get("channel_id"),
                    )
                    try:
                        self.bot.add_view(view, message_id=msg_id)
                    except Exception:
                        pass
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """Enregistre les messages des tickets dans le fichier JSON."""
        if message.author.bot:
            return
        apps = load_json(APPLICATIONS_FILE)
        updated = False
        for app_key, app in apps.items():
            if app.get("channel_id") == getattr(message.channel, "id", None):
                app.setdefault("messages", []).append({
                    "timestamp": datetime.now().isoformat(),
                    "author_id": message.author.id,
                    "content": message.content,
                    "attachments": [a.url for a in message.attachments],
                })
                apps[app_key] = app
                updated = True
                break
        if updated:
            save_json(APPLICATIONS_FILE, apps)

    @commands.command(name="postuler")
    async def postuler(self, ctx: commands.Context) -> None:
        """Ouvre le menu pour postuler à une division."""
        if not ctx.guild:
            await ctx.reply("⚠️ Cette commande fonctionne uniquement sur le serveur.", delete_after=5)
            return

        if get_division_by_member(ctx.author):
            await ctx.reply("❌ Tu es déjà dans une division. Utilise `d!quitter` pour la quitter d'abord.", delete_after=8)
            return

        embed = discord.Embed(
            title="📋 Système de Candidature",
            description=(
                "Sélectionne la division qui t'intéresse dans le menu ci-dessous.\n\n"
                "Un ticket privé sera créé et le capitaine pourra examiner ta candidature."
            ),
            color=discord.Color.blurple(),
        )
        if ctx.guild.icon:
            embed.set_thumbnail(url=ctx.guild.icon.url)

        view = DivisionSelectView(ctx.author, self.bot)
        await ctx.send(embed=embed, view=view)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(RecruitmentManager(bot))
