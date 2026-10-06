from __future__ import annotations
import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select, desc
from app.core.db import session_factory
from app.core.interactions import defer, respond
from app.models import Experience, Reputation, Member, EconomyAccount
from app.services.reputation import give_reputation
from app.core.exceptions import CooldownActive
from app.discord.theme import embed, money, number, bar, ledger


class ProgressionCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="profile", description="Mostra o perfil persistido do usuário.")
    @app_commands.guild_only()
    async def profile(self, interaction: discord.Interaction, user: discord.Member | None = None) -> None:
        guild = interaction.guild
        assert guild is not None
        await defer(interaction)
        target = user or interaction.user
        async with session_factory() as session:
            xp = (await session.execute(select(Experience).where(Experience.guild_id == guild.id, Experience.user_id == target.id))).scalar_one_or_none()
            rep = (await session.execute(select(Reputation).where(Reputation.guild_id == guild.id, Reputation.user_id == target.id))).scalar_one_or_none()
            account = (await session.execute(select(EconomyAccount).where(EconomyAccount.guild_id == guild.id, EconomyAccount.user_id == target.id))).scalar_one_or_none()
            member = (await session.execute(select(Member).where(Member.guild_id == guild.id, Member.user_id == target.id))).scalar_one_or_none()
        level = xp.level if xp else 0
        total_xp = xp.total_xp if xp else 0
        span = max(100 * (level + 1) ** 2, 1)
        previous_threshold = sum(100 * (step + 1) ** 2 for step in range(level))
        progress = max(total_xp - previous_threshold, 0)
        progress = min(progress, span)
        page = embed("BN / PERFIL", f"**{target.display_name}**\n{target.mention}\nNível `{level}` · XP `{number(total_xp)}`", "progression")
        page.set_thumbnail(url=target.display_avatar.url)
        page.add_field(name="Nível", value=f"`{level}`", inline=True)
        page.add_field(name="Reputação", value=f"`{number(rep.score if rep else 0)}`", inline=True)
        page.add_field(name="XP total", value=f"`{number(total_xp)}`", inline=True)
        page.add_field(name="Financeiro", value=ledger([
            ("Carteira", money(account.wallet) if account else money(0)),
            ("Banco", money(account.bank) if account else money(0)),
        ]), inline=False)
        page.add_field(name="Atividade", value=ledger([
            ("Mensagens", number(member.message_count if member else 0)),
            ("Voz", f"{number(member.voice_seconds if member else 0)}s"),
        ]), inline=False)
        page.add_field(name="Progresso do nível", value=f"{bar(progress, span)}\n`{number(progress)}/{number(span)}` XP", inline=False)
        await respond(interaction, embed=page)

    @app_commands.command(name="rep", description="Concede um ponto de reputação.")
    @app_commands.guild_only()
    async def rep(self, interaction: discord.Interaction, user: discord.Member, reason: str | None = None) -> None:
        guild = interaction.guild
        assert guild is not None
        if user.id == interaction.user.id:
            await respond(interaction, "Você não pode conceder reputação a si mesmo.", ephemeral=True)
            return
        if user.bot:
            await respond(interaction, "Bots não recebem reputação.", ephemeral=True)
            return
        await defer(interaction)
        try:
            async with session_factory() as session:
                await give_reputation(session, guild.id, interaction.user.id, user.id, reason[:500] if reason else None)
        except CooldownActive as exc:
            await respond(interaction, f"Você já concedeu reputação nesta janela. Aguarde {exc.seconds // 3600}h.", ephemeral=True)
            return
        page = embed("BN / REPUTAÇÃO", f"{user.mention} recebeu **+1** ponto.", "progression")
        page.add_field(name="Motivo", value=reason[:1024] if reason else "Não informado", inline=False)
        await respond(interaction, embed=page)

    @app_commands.command(name="reps", description="Mostra a reputação de um usuário.")
    @app_commands.guild_only()
    async def reps(self, interaction: discord.Interaction, user: discord.Member | None = None) -> None:
        guild = interaction.guild
        assert guild is not None
        await defer(interaction)
        target = user or interaction.user
        async with session_factory() as session:
            row = (await session.execute(select(Reputation).where(Reputation.guild_id == guild.id, Reputation.user_id == target.id))).scalar_one_or_none()
        score = row.score if row else 0
        page = embed("BN / REPUTAÇÃO", f"**{target.display_name}** · reputação registrada.", "progression")
        page.set_thumbnail(url=target.display_avatar.url)
        page.add_field(name="Pontuação", value=f"`{number(score)}`", inline=False)
        page.add_field(name="Leitura", value="Positiva" if score > 0 else "Neutra" if score == 0 else "Negativa", inline=True)
        await respond(interaction, embed=page)

    @app_commands.command(name="leaderboard", description="Mostra um ranking do servidor.")
    @app_commands.guild_only()
    @app_commands.choices(kind=[app_commands.Choice(name="XP", value="xp"), app_commands.Choice(name="Moedas", value="coins"), app_commands.Choice(name="Reputação", value="reputation"), app_commands.Choice(name="Mensagens", value="messages")])
    async def leaderboard(self, interaction: discord.Interaction, kind: app_commands.Choice[str]) -> None:
        guild = interaction.guild
        assert guild is not None
        await defer(interaction)
        async with session_factory() as session:
            if kind.value == "xp":
                result = await session.execute(select(Experience.user_id, Experience.total_xp).where(Experience.guild_id == guild.id).order_by(desc(Experience.total_xp)).limit(10))
                label = "XP"
            elif kind.value == "coins":
                value = EconomyAccount.wallet + EconomyAccount.bank
                result = await session.execute(select(EconomyAccount.user_id, value.label("value")).where(EconomyAccount.guild_id == guild.id).order_by(desc("value")).limit(10))
                label = "Moedas"
            elif kind.value == "reputation":
                result = await session.execute(select(Reputation.user_id, Reputation.score).where(Reputation.guild_id == guild.id).order_by(desc(Reputation.score)).limit(10))
                label = "Reputação"
            else:
                result = await session.execute(select(Member.user_id, Member.message_count).where(Member.guild_id == guild.id).order_by(desc(Member.message_count)).limit(10))
                label = "Mensagens"
            rows = result.all()
        page = embed("BN / RANKING", f"Top 10 por **{label}** neste servidor.", "progression")
        if not rows:
            page.add_field(name="Sem dados", value="Ainda não existem registros suficientes.", inline=False)
        else:
            medals = {1: "◆", 2: "◇", 3: "·"}
            lines = []
            top_value = max(int(rows[0][1]), 1)
            for position, (user_id, value) in enumerate(rows, start=1):
                user = guild.get_member(user_id)
                name = user.display_name if user else f"Usuário {user_id}"
                prefix = medals.get(position, f"{position:02d}.")
                lines.append(f"`{prefix}` **{name[:24]}**\n{bar(int(value), top_value, 10)} `{number(int(value))}`")
            page.add_field(name="Classificação", value="\n".join(lines)[:1024], inline=False)
        await respond(interaction, embed=page)
