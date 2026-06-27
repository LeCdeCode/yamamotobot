import discord
from discord.ext import commands
from discord.ui import View, Button
from typing import Optional

from .utils import (
    DIVISIONS, DIVISION_CAPTAIN_ROLE_ID,
    get_division_by_member, get_division_number,
    is_member_blocked, block_member_from_division,
    unblock_member_from_division, get_blocked_divisions,
    add_member_to_division, send_join_announcement, send_leave_announcement,
)


def _build_nickname(member: discord.Member, division_name: str) -> str:
    prefix = f"[Div {get_division_number(division_name)}] "
    base = member.nick or member.name
    if base.startswith(prefix):
        return base
    full = prefix + base
    return full if len(full) <= 32 else prefix + base[:32 - len(prefix)]


class InvitationView(View):
    def __init__(
        self,
        manager: "DivisionManager",
        member: discord.Member,
        division_name: str,
        division_role_id: int,
        captain_id: int,
    ) -> None:
        super().__init__(timeout=180.0)
        self.manager = manager
        self.member = member
        self.division_name = division_name
        self.division_role_id = division_role_id
        self.captain_id = captain_id
        self.message: Optional[discord.Message] = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.member.id:
            await interaction.response.send_message(
                "Seul le membre invité peut répondre à cette invitation.",
                ephemeral=True,
            )
            return False
        return True

    async def on_timeout(self) -> None:
        self.manager.end_invitation(self.captain_id)
        if not self.message:
            return
        embed = discord.Embed(
            title="⌛ Invitation expirée",
            description=f"{self.member.mention}, l'invitation à **{self.division_name}** a expiré.",
            color=discord.Color.dark_gray(),
        )
        for item in self.children:
            item.disabled = True
        try:
            await self.message.edit(embed=embed, view=self)
        except discord.HTTPException:
            pass

    @discord.ui.button(label="Accepter", style=discord.ButtonStyle.success, emoji="✅")
    async def accept_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.manager.end_invitation(self.captain_id)
        division_role = interaction.guild.get_role(self.division_role_id) if interaction.guild else None
        if not division_role:
            await interaction.response.send_message("Rôle de division introuvable.", ephemeral=True)
            return

        try:
            await self.member.add_roles(division_role, reason=f"Invitation acceptée — {self.division_name}")
        except discord.Forbidden:
            await interaction.response.send_message("Je n'ai pas les permissions pour ajouter le rôle.", ephemeral=True)
            return

        try:
            await self.member.edit(nick=_build_nickname(self.member, self.division_name))
        except discord.Forbidden:
            pass

        add_member_to_division(self.member.id, self.division_name)

        embed = discord.Embed(
            title="✅ Invitation acceptée",
            description=f"{self.member.mention} a rejoint **{self.division_name}** !",
            color=discord.Color.green(),
        )
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(embed=embed, view=self)
        await self.manager.send_join_announcement(self.member, self.division_name)

    @discord.ui.button(label="Refuser", style=discord.ButtonStyle.danger, emoji="❌")
    async def refuse_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.manager.end_invitation(self.captain_id)
        embed = discord.Embed(
            title="❌ Invitation refusée",
            description=f"{self.member.mention} a refusé l'invitation à **{self.division_name}**.",
            color=discord.Color.red(),
        )
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Bloquer cette division", style=discord.ButtonStyle.secondary, emoji="🚫")
    async def block_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.manager.end_invitation(self.captain_id)
        block_member_from_division(self.member.id, self.division_name)
        embed = discord.Embed(
            title="🚫 Division bloquée",
            description=(
                f"Tu as bloqué **{self.division_name}**. Tu ne recevras plus d'invitations de cette division.\n\n"
                f"Pour débloquer : `d!debloquer {get_division_number(self.division_name)}`"
            ),
            color=discord.Color.dark_red(),
        )
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(embed=embed, view=self)


class DivisionManager(commands.Cog):
    """Gestion des invitations et du blocage de divisions."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.active_invitations: dict[int, InvitationView] = {}

    def end_invitation(self, captain_id: int) -> None:
        self.active_invitations.pop(captain_id, None)

    async def send_join_announcement(self, member: discord.Member, division_name: str) -> None:
        """Envoie un message de bienvenue dans le salon 'entrants' de la division."""
        if not member.guild:
            return
        await send_join_announcement(member.guild, member, division_name)

    async def send_leave_announcement(self, member: discord.Member, division_name: str) -> None:
        """Envoie un message d'au revoir dans le salon 'sortants' de la division."""
        if not member.guild:
            return
        await send_leave_announcement(member.guild, member, division_name)

    @commands.command(name="inviter")
    async def inviter(self, ctx: commands.Context, member: discord.Member) -> None:
        """Invite un membre à rejoindre ta division. (Capitaine uniquement)"""
        if not ctx.guild:
            await ctx.reply("⚠️ Cette commande fonctionne uniquement sur le serveur.", delete_after=5)
            return

        if not ctx.author.get_role(DIVISION_CAPTAIN_ROLE_ID):
            await ctx.reply("❌ Seul un capitaine peut inviter des membres.", delete_after=5)
            return

        if member.bot:
            await ctx.reply("❌ Tu ne peux pas inviter un bot.", delete_after=5)
            return

        if member == ctx.author:
            await ctx.reply("❌ Tu ne peux pas t'inviter toi-même.", delete_after=5)
            return

        captain_division = get_division_by_member(ctx.author)
        if not captain_division:
            await ctx.reply("❌ Impossible de déterminer ta division.", delete_after=5)
            return

        division_name, division_data = captain_division

        if is_member_blocked(member.id, division_name):
            await ctx.reply(f"🚫 Ce membre a bloqué les invitations de **{division_name}**.", delete_after=5)
            return

        if any(member.get_role(d["role_id"]) for d in DIVISIONS.values()):
            await ctx.reply("❌ Ce membre appartient déjà à une division.", delete_after=5)
            return

        if ctx.author.id in self.active_invitations:
            await ctx.reply("⏳ Tu as déjà une invitation active. Attends qu'elle soit traitée.", delete_after=5)
            return

        entrants_channel = ctx.guild.get_channel(division_data["channels"]["entrants"])
        if not entrants_channel:
            await ctx.reply("❌ Salon des entrants introuvable.", delete_after=5)
            return

        embed = discord.Embed(
            title=f"📨 Invitation — {division_name}",
            description=f"{member.mention}, tu es invité(e) à rejoindre **{division_name}** par {ctx.author.mention}.",
            color=discord.Color.blurple(),
        )
        embed.add_field(name="⏱️ Validité", value="3 minutes", inline=True)
        embed.add_field(name="👑 Capitaine", value=ctx.author.mention, inline=True)
        embed.set_thumbnail(url=member.display_avatar.url)

        view = InvitationView(
            manager=self,
            member=member,
            division_name=division_name,
            division_role_id=division_data["role_id"],
            captain_id=ctx.author.id,
        )

        message = await entrants_channel.send(content=member.mention, embed=embed, view=view)
        view.message = message
        self.active_invitations[ctx.author.id] = view

        await ctx.reply(f"✅ Invitation envoyée dans {entrants_channel.mention}. Le membre a 3 minutes pour répondre.", delete_after=8)

    @commands.command(name="debloquer")
    async def debloquer(self, ctx: commands.Context, division_num: str) -> None:
        """Débloque une division pour recevoir ses invitations à nouveau."""
        if not ctx.guild:
            await ctx.reply("⚠️ Cette commande fonctionne uniquement sur le serveur.", delete_after=5)
            return

        division_name = f"Division {division_num}"
        blocked = get_blocked_divisions(ctx.author.id)

        if not blocked:
            await ctx.reply("ℹ️ Tu n'as bloqué aucune division.", delete_after=5)
            return

        if division_name not in blocked:
            await ctx.reply(f"ℹ️ Tu n'as pas bloqué **{division_name}**.", delete_after=5)
            return

        unblock_member_from_division(ctx.author.id, division_name)
        await ctx.reply(f"✅ **{division_name}** débloquée. Tu peux à nouveau recevoir ses invitations.", delete_after=8)

    @commands.command(name="bliste")
    async def bliste(self, ctx: commands.Context) -> None:
        """Affiche les divisions que tu as bloquées."""
        if not ctx.guild:
            await ctx.reply("⚠️ Cette commande fonctionne uniquement sur le serveur.", delete_after=5)
            return

        blocked = get_blocked_divisions(ctx.author.id)
        if not blocked:
            await ctx.reply("ℹ️ Tu n'as bloqué aucune division.", delete_after=5)
            return

        embed = discord.Embed(
            title="🚫 Divisions bloquées",
            description="\n".join(f"• **{div}** — `d!debloquer {get_division_number(div)}`" for div in blocked),
            color=discord.Color.dark_red(),
        )
        await ctx.reply(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(DivisionManager(bot))
