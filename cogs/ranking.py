import discord
from discord.ext import commands
from discord.ui import View, Button
from typing import Optional

from .utils import (
    DIVISIONS, DIVISION_CAPTAIN_ROLE_ID, LIEUTENANT_ROLE_ID, VICE_CAPTAIN_ROLE_ID,
    get_division_by_member, get_member_rank, set_member_rank,
    can_rank, set_rank_cooldown, get_rank_holder,
    is_member_banned, ban_member, unban_member,
    can_rejoin_after_kick, set_kick_cooldown,
    set_leave_cooldown, get_member_divisions,
    remove_member_from_division,
)


class ConfirmView(View):
    def __init__(self, user_id: int, danger: bool = False):
        super().__init__(timeout=60)
        self.user_id = user_id
        self.confirmed = False
        confirm_style = discord.ButtonStyle.danger if danger else discord.ButtonStyle.success

    @discord.ui.button(label="✅ Confirmer", style=discord.ButtonStyle.success)
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Seul l'auteur de la commande peut confirmer.", ephemeral=True)
            return
        self.confirmed = True
        await interaction.response.defer()
        self.stop()

    @discord.ui.button(label="❌ Annuler", style=discord.ButtonStyle.secondary)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Seul l'auteur de la commande peut annuler.", ephemeral=True)
            return
        await interaction.response.defer()
        self.stop()


class RankingManager(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def _is_captain(self, ctx: commands.Context) -> bool:
        return bool(ctx.author.get_role(DIVISION_CAPTAIN_ROLE_ID))

    # ──────────────────────────────────────────────
    # d!rank
    # ──────────────────────────────────────────────

    @commands.command(name="rank")
    async def rank(self, ctx: commands.Context, member: discord.Member, rank_type: int) -> None:
        """Promeut un membre : 1 = Lieutenant, 2 = Vice-Capitaine. (Capitaine uniquement)"""
        if not ctx.guild:
            await ctx.reply("⚠️ Cette commande fonctionne uniquement sur le serveur.", delete_after=5)
            return

        if not self._is_captain(ctx):
            await ctx.reply("❌ Seul un capitaine peut utiliser cette commande.", delete_after=5)
            return

        captain_division = get_division_by_member(ctx.author)
        if not captain_division:
            await ctx.reply("❌ Impossible de déterminer ta division.", delete_after=5)
            return

        division_name, _ = captain_division
        member_division = get_division_by_member(member)
        if not member_division or member_division[0] != division_name:
            await ctx.reply("❌ Ce membre n'est pas dans ta division.", delete_after=5)
            return

        if rank_type not in (1, 2):
            await ctx.reply("❌ Rang invalide. Utilise `1` pour Lieutenant ou `2` pour Vice-Capitaine.", delete_after=5)
            return

        rank_name   = "Lieutenant" if rank_type == 1 else "Vice-Capitaine"
        rank_role_id= LIEUTENANT_ROLE_ID if rank_type == 1 else VICE_CAPTAIN_ROLE_ID

        if not can_rank(ctx.author.id, division_name, rank_type):
            await ctx.reply(f"⏳ Tu dois attendre 10 jours avant de changer de {rank_name}.", delete_after=5)
            return

        existing = get_rank_holder(ctx.guild, division_name, rank_type)
        if existing and existing.id != member.id:
            await ctx.reply(
                f"❌ **{existing.mention}** est déjà {rank_name}. Utilise `d!unrank @{existing.name}` d'abord.",
                delete_after=8,
            )
            return

        embed = discord.Embed(
            title=f"⚔️ Promotion — {rank_name}",
            description=(
                f"Tu vas promouvoir {member.mention} en **{rank_name}** pour **{division_name}**.\n\n"
                f"⚠️ Cette action ne peut être refaite que dans 10 jours."
            ),
            color=discord.Color.gold(),
        )
        embed.set_thumbnail(url=member.display_avatar.url)

        view = ConfirmView(ctx.author.id)
        msg = await ctx.reply(embed=embed, view=view)
        await view.wait()

        if not view.confirmed:
            await msg.edit(content="❌ Action annulée.", embed=None, view=None)
            return

        try:
            rank_role = ctx.guild.get_role(rank_role_id)
            if rank_role:
                await member.add_roles(rank_role, reason=f"Promotion {rank_name} — {division_name}")
            set_member_rank(member.id, division_name, rank_name)
            set_rank_cooldown(ctx.author.id, division_name, rank_type)

            embed = discord.Embed(
                title=f"🎖️ {rank_name} nommé(e)",
                description=f"{member.mention} est maintenant **{rank_name}** de **{division_name}** !",
                color=discord.Color.green(),
            )
            embed.set_thumbnail(url=member.display_avatar.url)
            await msg.edit(embed=embed, view=None)

            try:
                await member.send(f"🎉 Félicitations ! Tu es maintenant **{rank_name}** de **{division_name}** !")
            except discord.Forbidden:
                pass
        except discord.Forbidden:
            await msg.edit(content="❌ Permissions insuffisantes pour modifier les rôles.", embed=None, view=None)

    # ──────────────────────────────────────────────
    # d!unrank
    # ──────────────────────────────────────────────

    @commands.command(name="unrank")
    async def unrank(self, ctx: commands.Context, member: discord.Member) -> None:
        """Retire le rang d'un membre. (Capitaine uniquement)"""
        if not ctx.guild:
            await ctx.reply("⚠️ Cette commande fonctionne uniquement sur le serveur.", delete_after=5)
            return

        if not self._is_captain(ctx):
            await ctx.reply("❌ Seul un capitaine peut utiliser cette commande.", delete_after=5)
            return

        member_division = get_division_by_member(member)
        if not member_division:
            await ctx.reply("❌ Ce membre n'est dans aucune division.", delete_after=5)
            return

        division_name, _ = member_division
        rank = get_member_rank(member.id, division_name)
        if not rank:
            await ctx.reply("❌ Ce membre n'a aucun rang.", delete_after=5)
            return

        try:
            for role_id in (LIEUTENANT_ROLE_ID, VICE_CAPTAIN_ROLE_ID):
                role = ctx.guild.get_role(role_id)
                if role and role in member.roles:
                    await member.remove_roles(role, reason="Retrait de rang")
            set_member_rank(member.id, division_name, None)

            embed = discord.Embed(
                title="📉 Rang retiré",
                description=f"{member.mention} a perdu son rang de **{rank}**.",
                color=discord.Color.orange(),
            )
            await ctx.reply(embed=embed)

            try:
                await member.send(f"⚠️ Tu as perdu ton rang de **{rank}** dans **{division_name}**.")
            except discord.Forbidden:
                pass
        except discord.Forbidden:
            await ctx.reply("❌ Permissions insuffisantes.", delete_after=5)

    # ──────────────────────────────────────────────
    # d!kick
    # ──────────────────────────────────────────────

    @commands.command(name="kick")
    async def kick(self, ctx: commands.Context, member: discord.Member) -> None:
        """Expulse un membre de ta division. (Capitaine uniquement)"""
        if not ctx.guild:
            await ctx.reply("⚠️ Cette commande fonctionne uniquement sur le serveur.", delete_after=5)
            return

        if not self._is_captain(ctx):
            await ctx.reply("❌ Seul un capitaine peut expulser des membres.", delete_after=5)
            return

        captain_division = get_division_by_member(ctx.author)
        if not captain_division:
            await ctx.reply("❌ Impossible de déterminer ta division.", delete_after=5)
            return

        member_division = get_division_by_member(member)
        if not member_division or member_division[0] != captain_division[0]:
            await ctx.reply("❌ Ce membre n'est pas dans ta division.", delete_after=5)
            return

        division_name = captain_division[0]

        embed = discord.Embed(
            title="⚠️ Confirmation — Expulsion",
            description=(
                f"Tu vas expulser {member.mention} de **{division_name}**.\n\n"
                "Il/elle ne pourra repostuler qu'après 3 jours."
            ),
            color=discord.Color.orange(),
        )
        embed.set_thumbnail(url=member.display_avatar.url)

        view = ConfirmView(ctx.author.id, danger=True)
        msg = await ctx.reply(embed=embed, view=view)
        await view.wait()

        if not view.confirmed:
            await msg.edit(content="❌ Action annulée.", embed=None, view=None)
            return

        try:
            division_data = DIVISIONS[division_name]
            role = ctx.guild.get_role(division_data["role_id"])
            if role:
                await member.remove_roles(role, reason="Expulsion")

            for role_id in (LIEUTENANT_ROLE_ID, VICE_CAPTAIN_ROLE_ID):
                r = ctx.guild.get_role(role_id)
                if r and r in member.roles:
                    await member.remove_roles(r, reason="Expulsion — retrait grade")

            set_member_rank(member.id, division_name, None)
            remove_member_from_division(member.id, division_name)
            set_kick_cooldown(member.id, division_name)

            try:
                await member.edit(nick=None, reason="Expulsion")
            except discord.Forbidden:
                pass

            embed = discord.Embed(
                title="✅ Membre expulsé",
                description=f"{member.mention} a été expulsé(e) de **{division_name}**.",
                color=discord.Color.red(),
            )
            await msg.edit(embed=embed, view=None)

            try:
                await member.send(f"⚠️ Tu as été expulsé(e) de **{division_name}**. Tu pourras repostuler dans 3 jours.")
            except discord.Forbidden:
                pass
        except discord.Forbidden:
            await msg.edit(content="❌ Permissions insuffisantes.", embed=None, view=None)

    # ──────────────────────────────────────────────
    # d!ban
    # ──────────────────────────────────────────────

    @commands.command(name="ban")
    async def ban(self, ctx: commands.Context, member: discord.Member) -> None:
        """Bannit un membre de toutes les divisions. (Capitaine uniquement)"""
        if not ctx.guild:
            await ctx.reply("⚠️ Cette commande fonctionne uniquement sur le serveur.", delete_after=5)
            return

        if not self._is_captain(ctx):
            await ctx.reply("❌ Seul un capitaine peut bannir des membres.", delete_after=5)
            return

        if is_member_banned(member.id):
            await ctx.reply(f"ℹ️ {member.mention} est déjà banni(e).", delete_after=5)
            return

        embed = discord.Embed(
            title="🚫 Confirmation — Bannissement",
            description=(
                f"Tu vas bannir {member.mention} de **toutes les divisions**.\n\n"
                "Il/elle ne pourra plus postuler jusqu'au débannissement."
            ),
            color=discord.Color.dark_red(),
        )
        embed.set_thumbnail(url=member.display_avatar.url)

        view = ConfirmView(ctx.author.id, danger=True)
        msg = await ctx.reply(embed=embed, view=view)
        await view.wait()

        if not view.confirmed:
            await msg.edit(content="❌ Action annulée.", embed=None, view=None)
            return

        try:
            ban_member(member.id)
            for div_name, div_data in DIVISIONS.items():
                role = ctx.guild.get_role(div_data["role_id"])
                if role and role in member.roles:
                    await member.remove_roles(role, reason="Ban définitif")
            for role_id in (LIEUTENANT_ROLE_ID, VICE_CAPTAIN_ROLE_ID):
                r = ctx.guild.get_role(role_id)
                if r and r in member.roles:
                    await member.remove_roles(r, reason="Ban définitif")

            embed = discord.Embed(
                title="🚫 Membre banni",
                description=f"{member.mention} est banni(e) de toutes les divisions.",
                color=discord.Color.dark_red(),
            )
            await msg.edit(embed=embed, view=None)

            try:
                await member.send("🚫 Tu as été banni(e) et ne peux plus postuler à aucune division.")
            except discord.Forbidden:
                pass
        except discord.Forbidden:
            await msg.edit(content="❌ Permissions insuffisantes.", embed=None, view=None)

    # ──────────────────────────────────────────────
    # d!deban
    # ──────────────────────────────────────────────

    @commands.command(name="deban")
    async def deban(self, ctx: commands.Context, member: discord.Member) -> None:
        """Débannit un membre. (Capitaine uniquement)"""
        if not ctx.guild:
            await ctx.reply("⚠️ Cette commande fonctionne uniquement sur le serveur.", delete_after=5)
            return

        if not self._is_captain(ctx):
            await ctx.reply("❌ Seul un capitaine peut débannir des membres.", delete_after=5)
            return

        if not is_member_banned(member.id):
            await ctx.reply(f"ℹ️ {member.mention} n'est pas banni(e).", delete_after=5)
            return

        unban_member(member.id)

        embed = discord.Embed(
            title="✅ Membre débanni",
            description=f"{member.mention} peut à nouveau postuler à des divisions.",
            color=discord.Color.green(),
        )
        await ctx.reply(embed=embed)

        try:
            await member.send("✅ Tu as été débanni(e) et peux de nouveau postuler !")
        except discord.Forbidden:
            pass

    # ──────────────────────────────────────────────
    # d!quitter
    # ──────────────────────────────────────────────

    @commands.command(name="quitter")
    async def quitter(self, ctx: commands.Context) -> None:
        """Quitte ta division actuelle."""
        if not ctx.guild:
            await ctx.reply("⚠️ Cette commande fonctionne uniquement sur le serveur.", delete_after=5)
            return

        member_division = get_division_by_member(ctx.author)
        if not member_division:
            await ctx.reply("❌ Tu n'es dans aucune division.", delete_after=5)
            return

        division_name, division_data = member_division

        embed = discord.Embed(
            title="⚠️ Confirmation — Quitter la division",
            description=(
                f"Tu vas quitter **{division_name}**.\n\n"
                "Tu ne pourras repostuler qu'après 3 jours."
            ),
            color=discord.Color.orange(),
        )

        view = ConfirmView(ctx.author.id)
        msg = await ctx.reply(embed=embed, view=view)
        await view.wait()

        if not view.confirmed:
            await msg.edit(content="❌ Action annulée.", embed=None, view=None)
            return

        try:
            role = ctx.guild.get_role(division_data["role_id"])
            if role:
                await ctx.author.remove_roles(role, reason="Départ volontaire")

            for role_id in (LIEUTENANT_ROLE_ID, VICE_CAPTAIN_ROLE_ID):
                r = ctx.guild.get_role(role_id)
                if r and r in ctx.author.roles:
                    await ctx.author.remove_roles(r, reason="Départ — retrait grade")

            set_member_rank(ctx.author.id, division_name, None)
            remove_member_from_division(ctx.author.id, division_name)
            set_leave_cooldown(ctx.author.id)

            try:
                await ctx.author.edit(nick=None, reason="Départ de division")
            except discord.Forbidden:
                pass

            embed = discord.Embed(
                title="👋 Division quittée",
                description=f"Tu as quitté **{division_name}**. Tu pourras repostuler dans 3 jours.",
                color=discord.Color.blurple(),
            )
            await msg.edit(embed=embed, view=None)
        except discord.Forbidden:
            await msg.edit(content="❌ Permissions insuffisantes.", embed=None, view=None)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(RankingManager(bot))
