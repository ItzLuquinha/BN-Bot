from __future__ import annotations
from decimal import Decimal
import math
import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select
from app.core.db import session_factory
from app.core.interactions import defer, respond
from app.models import ShopItem, InventoryItem, UserJob, Job, Experience
from app.repositories.economy import get_shop_items, buy_item, sell_item
from app.repositories.guilds import ensure_guild, ensure_user, ensure_member
from app.services.economy import economy_service
from app.services.cooldowns import check_and_set
from app.core.time import utc_now
from app.services.rewards import claim_reward
from app.core.exceptions import CooldownActive
from app.discord.theme import embed, money, number, bar, percent, ledger, compact_money, status_line


MAX_TRANSACTION = 1_000_000_000.0


class EconomyCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @staticmethod
    def guild_and_member(interaction: discord.Interaction) -> tuple[discord.Guild, discord.Member]:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            raise RuntimeError("guild context required")
        return interaction.guild, interaction.user

    async def ensure_context(self, session, guild: discord.Guild, member: discord.Member) -> None:
        await ensure_guild(session, guild.id, guild.name, guild.owner_id, guild.icon.url if guild.icon else None)
        await ensure_user(session, member.id, member.name, member.display_name, member.display_avatar.url, member.banner.url if member.banner else None, member.bot)
        await ensure_member(session, guild.id, member.id, member.joined_at)

    @staticmethod
    def valid_amount(amount: float) -> bool:
        return math.isfinite(amount) and 0 < amount <= MAX_TRANSACTION

    @app_commands.command(name="balance", description="Mostra carteira e banco.")
    @app_commands.guild_only()
    async def balance(self, interaction: discord.Interaction, user: discord.Member | None = None) -> None:
        guild, member = self.guild_and_member(interaction)
        target = user or member
        await defer(interaction)
        async with session_factory() as session:
            await self.ensure_context(session, guild, target)
            data = await economy_service.balance(session, guild.id, target.id)
        total = data["total"]
        page = embed("BN / CARTEIRA", f"**{target.display_name}** · leitura financeira do servidor.", "economy")
        page.set_thumbnail(url=target.display_avatar.url)
        page.add_field(name="Patrimônio", value=f"**{money(total)}**", inline=False)
        page.add_field(name="Mapa do saldo", value=ledger([
            ("Carteira", money(data["wallet"])),
            ("Banco", money(data["bank"])),
            ("Total", money(total)),
        ]), inline=False)
        page.add_field(name="Liquidez", value=f"{bar(data['wallet'], total)}\nCarteira `{percent(data['wallet'], total)}` · Banco `{percent(data['bank'], total)}`", inline=False)
        await respond(interaction, embed=page)

    @app_commands.command(name="bank", description="Mostra o saldo do banco.")
    @app_commands.guild_only()
    async def bank(self, interaction: discord.Interaction) -> None:
        guild, member = self.guild_and_member(interaction)
        await defer(interaction)
        async with session_factory() as session:
            await self.ensure_context(session, guild, member)
            data = await economy_service.balance(session, guild.id, member.id)
        page = embed("BN / BANCO", f"**{member.display_name}** · reserva guardada.", "economy")
        page.add_field(name="Saldo bancário", value=money(data["bank"]), inline=True)
        page.add_field(name="Carteira", value=money(data["wallet"]), inline=True)
        page.add_field(name="Total", value=money(data["total"]), inline=True)
        page.add_field(name="Distribuição", value=f"{bar(data['wallet'], data['total'])}\nCarteira {percent(data['wallet'], data['total'])} · Banco {percent(data['bank'], data['total'])}", inline=False)
        await respond(interaction, embed=page)

    @app_commands.command(name="deposit", description="Deposita moedas no banco.")
    @app_commands.guild_only()
    async def deposit(self, interaction: discord.Interaction, amount: app_commands.Range[float, 0.01, MAX_TRANSACTION]) -> None:
        guild, member = self.guild_and_member(interaction)
        if not self.valid_amount(amount):
            await respond(interaction, "O valor precisa estar entre 0,01 e 1.000.000.000,00 moedas.", ephemeral=True)
            return
        await defer(interaction)
        async with session_factory() as session:
            await self.ensure_context(session, guild, member)
            data = await economy_service.deposit(session, guild.id, member.id, Decimal(str(amount)))
        page = embed("BN / DEPÓSITO", "Movimentação concluída.", "economy")
        page.add_field(name="Movido", value=money(Decimal(str(amount))), inline=True)
        page.add_field(name="Carteira", value=money(data["wallet"]), inline=True)
        page.add_field(name="Banco", value=money(data["bank"]), inline=True)
        await respond(interaction, embed=page)

    @app_commands.command(name="withdraw", description="Saca moedas do banco.")
    @app_commands.guild_only()
    async def withdraw(self, interaction: discord.Interaction, amount: app_commands.Range[float, 0.01, MAX_TRANSACTION]) -> None:
        guild, member = self.guild_and_member(interaction)
        if not self.valid_amount(amount):
            await respond(interaction, "O valor precisa estar entre 0,01 e 1.000.000.000,00 moedas.", ephemeral=True)
            return
        await defer(interaction)
        async with session_factory() as session:
            await self.ensure_context(session, guild, member)
            data = await economy_service.withdraw(session, guild.id, member.id, Decimal(str(amount)))
        page = embed("BN / SAQUE", "Movimentação concluída.", "economy")
        page.add_field(name="Movido", value=money(Decimal(str(amount))), inline=True)
        page.add_field(name="Carteira", value=money(data["wallet"]), inline=True)
        page.add_field(name="Banco", value=money(data["bank"]), inline=True)
        await respond(interaction, embed=page)

    @app_commands.command(name="pay", description="Transfere moedas para outro usuário.")
    @app_commands.guild_only()
    async def pay(self, interaction: discord.Interaction, user: discord.Member, amount: app_commands.Range[float, 0.01, MAX_TRANSACTION]) -> None:
        guild, member = self.guild_and_member(interaction)
        if user.id == member.id:
            await respond(interaction, "Você não pode transferir moedas para si mesmo.", ephemeral=True)
            return
        if user.bot:
            await respond(interaction, "Contas de bot não podem receber transferências.", ephemeral=True)
            return
        if not self.valid_amount(amount):
            await respond(interaction, "O valor precisa estar entre 0,01 e 1.000.000.000,00 moedas.", ephemeral=True)
            return
        await defer(interaction)
        async with session_factory() as session:
            await self.ensure_context(session, guild, member)
            await self.ensure_context(session, guild, user)
            await economy_service.transfer(session, guild.id, member.id, user.id, Decimal(str(amount)))
        page = embed("BN / TRANSFERÊNCIA", "Movimentação concluída entre duas carteiras.", "economy")
        page.add_field(name="Origem", value=member.mention, inline=True)
        page.add_field(name="Destino", value=user.mention, inline=True)
        page.add_field(name="Valor", value=money(Decimal(str(amount))), inline=True)
        await respond(interaction, embed=page)

    @app_commands.command(name="daily", description="Recebe a recompensa diária.")
    @app_commands.guild_only()
    async def daily(self, interaction: discord.Interaction) -> None:
        guild, member = self.guild_and_member(interaction)
        await defer(interaction)
        try:
            async with session_factory() as session:
                await self.ensure_context(session, guild, member)
                amount, streak = await claim_reward(session, guild.id, member.id, "daily", Decimal("250"))
                await session.commit()
        except CooldownActive as exc:
            await respond(interaction, f"A recompensa diária já foi coletada. Próxima janela em {exc.seconds // 3600}h.", ephemeral=True)
            return
        page = embed("BN / DAILY", "Recompensa diária confirmada.", "economy")
        page.add_field(name="Recebido", value=money(amount), inline=True)
        page.add_field(name="Streak", value=f"`{streak}` dias", inline=True)
        page.add_field(name="Bônus", value=f"+{min(max(streak - 1, 0) * 5, 100)}%", inline=True)
        page.add_field(name="Sequência", value=f"{bar(min(streak, 20), 20)}\n`{min(streak, 20)}/20` dias", inline=False)
        page.add_field(name="Próxima janela", value="Amanhã", inline=False)
        await respond(interaction, embed=page)

    @app_commands.command(name="weekly", description="Recebe a recompensa semanal.")
    @app_commands.guild_only()
    async def weekly(self, interaction: discord.Interaction) -> None:
        guild, member = self.guild_and_member(interaction)
        await defer(interaction)
        try:
            async with session_factory() as session:
                await self.ensure_context(session, guild, member)
                amount, streak = await claim_reward(session, guild.id, member.id, "weekly", Decimal("1500"))
                await session.commit()
        except CooldownActive as exc:
            await respond(interaction, f"A recompensa semanal já foi coletada. Próxima janela em {exc.seconds // 86400}d.", ephemeral=True)
            return
        page = embed("BN / WEEKLY", "Recompensa semanal confirmada.", "economy")
        page.add_field(name="Recebido", value=money(amount), inline=True)
        page.add_field(name="Streak", value=f"`{streak}` semanas", inline=True)
        page.add_field(name="Bônus", value=f"+{min(max(streak - 1, 0) * 5, 100)}%", inline=True)
        page.add_field(name="Sequência", value=f"{bar(min(streak, 12), 12)}\n`{min(streak, 12)}/12` semanas", inline=False)
        await respond(interaction, embed=page)

    @app_commands.command(name="shop", description="Lista os itens da loja.")
    @app_commands.guild_only()
    async def shop(self, interaction: discord.Interaction) -> None:
        guild, _ = self.guild_and_member(interaction)
        await defer(interaction)
        async with session_factory() as session:
            items = await get_shop_items(session, guild.id)
        page = embed("BN / LOJA", "Catálogo atual do servidor.", "economy")
        if not items:
            page.add_field(name="Catálogo vazio", value="Nenhum item foi publicado ainda.", inline=False)
        else:
            rarity_icons = {"common": "○", "uncommon": "◇", "rare": "◆", "epic": "✦", "legendary": "✧"}
            for item in items[:25]:
                stock = "∞" if item.stock is None else number(item.stock)
                icon = rarity_icons.get(str(item.rarity).casefold(), "·")
                page.add_field(name=f"{icon} #{item.id} · {item.name}", value=f"**{money(item.price)}**\nEstoque `{stock}` · `{item.category}`", inline=True)
            if len(items) > 25:
                page.set_footer(text=f"BN Bot · economia · mostrando 25 de {len(items)} itens")
        await respond(interaction, embed=page)

    @app_commands.command(name="buy", description="Compra um item da loja.")
    @app_commands.guild_only()
    async def buy(self, interaction: discord.Interaction, item_id: int, quantity: app_commands.Range[int, 1, 99] = 1) -> None:
        guild, member = self.guild_and_member(interaction)
        await defer(interaction)
        async with session_factory() as session:
            await self.ensure_context(session, guild, member)
            item = await buy_item(session, guild.id, member.id, item_id, quantity)
            await session.commit()
        total = item.price * quantity
        page = embed("BN / COMPRA", "Transação registrada e item adicionado ao inventário.", "economy")
        page.add_field(name="Item", value=f"`{item.id}` · {item.name}", inline=False)
        page.add_field(name="Quantidade", value=f"`{quantity}x`", inline=True)
        page.add_field(name="Total", value=money(total), inline=True)
        await respond(interaction, embed=page)

    @app_commands.command(name="sell", description="Vende um item da loja.")
    @app_commands.guild_only()
    async def sell(self, interaction: discord.Interaction, item_id: int, quantity: app_commands.Range[int, 1, 99] = 1) -> None:
        guild, member = self.guild_and_member(interaction)
        await defer(interaction)
        async with session_factory() as session:
            await self.ensure_context(session, guild, member)
            value = await sell_item(session, guild.id, member.id, item_id, quantity)
            await session.commit()
        page = embed("BN / VENDA", "Item devolvido ao mercado por 50% do preço.", "economy")
        page.add_field(name="Item", value=f"`{item_id}`", inline=True)
        page.add_field(name="Quantidade", value=f"`{quantity}x`", inline=True)
        page.add_field(name="Recebido", value=money(value), inline=True)
        await respond(interaction, embed=page)

    @app_commands.command(name="inventory", description="Mostra o inventário.")
    @app_commands.guild_only()
    async def inventory(self, interaction: discord.Interaction) -> None:
        guild, member = self.guild_and_member(interaction)
        await defer(interaction)
        async with session_factory() as session:
            await self.ensure_context(session, guild, member)
            result = await session.execute(select(InventoryItem, ShopItem).join(ShopItem, InventoryItem.shop_item_id == ShopItem.id).where(InventoryItem.guild_id == guild.id, InventoryItem.user_id == member.id, InventoryItem.quantity > 0).order_by(ShopItem.name.asc()))
            rows = result.all()
        page = embed("BN / INVENTÁRIO", f"Itens guardados por **{member.display_name}**.", "economy")
        if not rows:
            page.add_field(name="Vazio", value="Nenhum item em posse.", inline=False)
        else:
            for inv, item in rows[:25]:
                value = Decimal(item.price) * inv.quantity
                page.add_field(name=item.name, value=ledger([("Quantidade", f"{inv.quantity}x"), ("Preço", money(item.price)), ("Valor", money(value))]), inline=True)
        await respond(interaction, embed=page)

    @app_commands.command(name="jobs", description="Lista os empregos do servidor.")
    @app_commands.guild_only()
    async def jobs(self, interaction: discord.Interaction) -> None:
        guild, _ = self.guild_and_member(interaction)
        await defer(interaction)
        async with session_factory() as session:
            result = await session.execute(select(Job).where(Job.guild_id == guild.id).order_by(Job.salary.desc()))
            rows = result.scalars().all()
        page = embed("BN / EMPREGOS", "Mercado de trabalho do servidor.", "economy")
        if not rows:
            page.add_field(name="Sem vagas", value="Nenhum emprego foi configurado.", inline=False)
        else:
            for row in rows[:25]:
                try:
                    required_level = max(int(row.requirements.get("level", 0)), 0) if isinstance(row.requirements, dict) else 0
                except (TypeError, ValueError):
                    required_level = 0
                page.add_field(name=f"{row.name} · `{row.key}`", value=f"Salário {money(row.salary)}\nXP `{row.xp_reward}` · nível `{required_level}`", inline=True)
        await respond(interaction, embed=page)

    @app_commands.command(name="job", description="Escolhe um emprego.")
    @app_commands.guild_only()
    async def job(self, interaction: discord.Interaction, key: str) -> None:
        guild, member = self.guild_and_member(interaction)
        key = key.strip().casefold()
        if not key or len(key) > 32:
            await respond(interaction, "Informe uma chave de emprego válida.", ephemeral=True)
            return
        await defer(interaction)
        async with session_factory() as session:
            await self.ensure_context(session, guild, member)
            job = (await session.execute(select(Job).where(Job.guild_id == guild.id, Job.key == key))).scalar_one_or_none()
            if job is None:
                await respond(interaction, "Emprego não encontrado.", ephemeral=True)
                return
            required_level = int(job.requirements.get("level", 0)) if isinstance(job.requirements, dict) else 0
            xp = (await session.execute(select(Experience).where(Experience.guild_id == guild.id, Experience.user_id == member.id))).scalar_one_or_none()
            if (xp.level if xp else 0) < required_level:
                await respond(interaction, f"Este emprego exige nível {required_level}.", ephemeral=True)
                return
            user_job = (await session.execute(select(UserJob).where(UserJob.guild_id == guild.id, UserJob.user_id == member.id).with_for_update())).scalar_one_or_none()
            if user_job is None:
                user_job = UserJob(guild_id=guild.id, user_id=member.id, job_id=job.id, level=1, xp=0)
                session.add(user_job)
            else:
                user_job.job_id = job.id
                user_job.level = 1
                user_job.xp = 0
            await session.commit()
        page = embed("BN / EMPREGO EQUIPADO", f"**{job.name}** está agora equipado.", "economy")
        page.add_field(name="Chave", value=f"`{job.key}`", inline=True)
        page.add_field(name="Salário base", value=money(job.salary), inline=True)
        page.add_field(name="XP por turno", value=f"`{job.xp_reward}`", inline=True)
        await respond(interaction, embed=page)

    @app_commands.command(name="work", description="Trabalha no emprego equipado.")
    @app_commands.guild_only()
    async def work(self, interaction: discord.Interaction) -> None:
        guild, member = self.guild_and_member(interaction)
        await defer(interaction)
        async with session_factory() as session:
            await self.ensure_context(session, guild, member)
            result = await session.execute(select(UserJob, Job).join(Job, UserJob.job_id == Job.id).where(UserJob.guild_id == guild.id, UserJob.user_id == member.id))
            row = result.one_or_none()
            if row is None:
                await respond(interaction, "Você ainda não possui um emprego configurado.", ephemeral=True)
                return
            user_job, job = row
            cooldown = await check_and_set(f"bn:work:{guild.id}:{member.id}", 3600)
            if cooldown:
                await respond(interaction, f"Você já trabalhou recentemente. Aguarde {cooldown}s.", ephemeral=True)
                return
            reward = job.salary * (Decimal("1") + Decimal(max(user_job.level - 1, 0)) * Decimal("0.05"))
            user_job.xp += job.xp_reward
            threshold = max(user_job.level, 1) * 100
            while user_job.xp >= threshold:
                user_job.xp -= threshold
                user_job.level += 1
                threshold = max(user_job.level, 1) * 100
            user_job.last_work_at = utc_now()
            await economy_service.credit(session, guild.id, member.id, reward, "work", job.name)
            next_xp = max(user_job.level, 1) * 100
            current_xp = user_job.xp
            job_level = user_job.level
        page = embed("BN / TURNO CONCLUÍDO", f"**{job.name}** · trabalho registrado.", "economy")
        page.add_field(name="Recebido", value=money(reward), inline=True)
        page.add_field(name="Nível do emprego", value=f"`{job_level}`", inline=True)
        page.add_field(name="Próximo turno", value=status_line("Cooldown", "1h" , "pending"), inline=True)
        page.add_field(name="Progresso", value=f"{bar(current_xp, next_xp)}\n`{current_xp}/{next_xp}` XP", inline=False)
        await respond(interaction, embed=page)
