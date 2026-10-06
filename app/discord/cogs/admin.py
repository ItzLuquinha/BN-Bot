from __future__ import annotations
import logging
from decimal import Decimal
import math
import re
import secrets
import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from app.core.db import session_factory
from app.core.time import utc_now
from app.core.interactions import defer, respond
from app.models import AuditLog, GuildSettings, ShopItem, Job
from app.repositories.guilds import ensure_guild, ensure_user, ensure_member
from app.services.economy import economy_service
from app.discord.theme import embed, money, ledger

logger = logging.getLogger("bn_bot.discord.admin")

admin_group = app_commands.Group(name="admin", description="Administração do BN Bot.")
MAX_ADMIN_AMOUNT = 1_000_000_000.0


class AdminCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def audit(self, guild_id: int, executor_id: int, action: str, resource: str, before: dict | None, after: dict | None) -> None:
        try:
            async with session_factory() as session:
                session.add(AuditLog(id=secrets.randbits(62), guild_id=guild_id, executor_id=executor_id, action=action, resource=resource, before_state=before, after_state=after, created_at=utc_now()))
                await session.commit()
        except Exception:
            logger.exception("audit persistence failed action=%s resource=%s", action, resource)

    @staticmethod
    def valid_amount(amount: float) -> bool:
        return math.isfinite(amount) and 0 < amount <= MAX_ADMIN_AMOUNT

    @admin_group.command(name="credit", description="Adiciona moedas a um usuário.")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_guild=True)
    async def credit(self, interaction: discord.Interaction, user: discord.Member, amount: app_commands.Range[float, 0.01, MAX_ADMIN_AMOUNT], note: str | None = None) -> None:
        if not self.valid_amount(amount):
            await respond(interaction, "O valor deve estar entre 0,01 e 1.000.000.000,00.", ephemeral=True)
            return
        guild = interaction.guild
        assert guild is not None
        await defer(interaction)
        async with session_factory() as session:
            await ensure_guild(session, guild.id, guild.name, guild.owner_id, guild.icon.url if guild.icon else None)
            await ensure_user(session, user.id, user.name, user.display_name, user.display_avatar.url, user.banner.url if user.banner else None, user.bot)
            await ensure_member(session, guild.id, user.id, user.joined_at)
            await economy_service.credit(session, guild.id, user.id, Decimal(str(amount)), "admin_credit", note[:500] if note else None)
        await self.audit(guild.id, interaction.user.id, "economy.credit", f"user:{user.id}", None, {"amount": str(amount), "note": note})
        page = embed("BN / CRÉDITO", f"{user.mention} recebeu moedas administrativas.", "admin")
        page.add_field(name="Operação", value=ledger([("Usuário", str(user.id)), ("Valor", money(amount))]), inline=False)
        page.add_field(name="Nota", value=note[:1024] if note else "Não informada", inline=False)
        await respond(interaction, embed=page)

    @admin_group.command(name="debit", description="Remove moedas de um usuário.")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_guild=True)
    async def debit(self, interaction: discord.Interaction, user: discord.Member, amount: app_commands.Range[float, 0.01, MAX_ADMIN_AMOUNT], note: str | None = None) -> None:
        if not self.valid_amount(amount):
            await respond(interaction, "O valor deve estar entre 0,01 e 1.000.000.000,00.", ephemeral=True)
            return
        guild = interaction.guild
        assert guild is not None
        await defer(interaction)
        async with session_factory() as session:
            await ensure_guild(session, guild.id, guild.name, guild.owner_id, guild.icon.url if guild.icon else None)
            await ensure_user(session, user.id, user.name, user.display_name, user.display_avatar.url, user.banner.url if user.banner else None, user.bot)
            await ensure_member(session, guild.id, user.id, user.joined_at)
            await economy_service.debit(session, guild.id, user.id, Decimal(str(amount)), "admin_debit", note[:500] if note else None)
        await self.audit(guild.id, interaction.user.id, "economy.debit", f"user:{user.id}", None, {"amount": str(amount), "note": note})
        page = embed("BN / DÉBITO", f"{user.mention} teve moedas removidas.", "admin")
        page.add_field(name="Operação", value=ledger([("Usuário", str(user.id)), ("Valor", money(amount))]), inline=False)
        page.add_field(name="Nota", value=note[:1024] if note else "Não informada", inline=False)
        await respond(interaction, embed=page)

    @admin_group.command(name="shop-add", description="Cria um item na loja.")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_guild=True)
    async def shop_add(self, interaction: discord.Interaction, name: str, price: app_commands.Range[float, 0.01, MAX_ADMIN_AMOUNT], category: str, stock: app_commands.Range[int, 0, 1_000_000] | None = None) -> None:
        name = " ".join(name.split())
        category = " ".join(category.split())
        if not name or len(name) > 100 or not category or len(category) > 50 or not self.valid_amount(price):
            await respond(interaction, "Nome, categoria e preço não atendem aos limites da loja.", ephemeral=True)
            return
        guild = interaction.guild
        assert guild is not None
        await defer(interaction)
        async with session_factory() as session:
            duplicate = await session.scalar(select(ShopItem.id).where(ShopItem.guild_id == guild.id, func.lower(ShopItem.name) == name.casefold()).limit(1))
            if duplicate is not None:
                await respond(interaction, "Já existe um item com esse nome nesta loja.", ephemeral=True)
                return
            row = ShopItem(guild_id=guild.id, name=name, description="", category=category, rarity="common", price=Decimal(str(price)), stock=stock, stack_limit=99, metadata_json={}, created_at=utc_now(), updated_at=utc_now())
            session.add(row)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                await respond(interaction, "O item não pôde ser criado porque o nome já existe.", ephemeral=True)
                return
            item_id = row.id
        await self.audit(guild.id, interaction.user.id, "shop.create", f"item:{item_id}", None, {"name": name, "price": str(price), "category": category, "stock": stock})
        page = embed("BN / ITEM PUBLICADO", f"**{name}** entrou na loja.", "admin")
        page.add_field(name="ID", value=f"`{item_id}`", inline=True)
        page.add_field(name="Preço", value=money(price), inline=True)
        page.add_field(name="Estoque", value="∞" if stock is None else f"`{stock}`", inline=True)
        await respond(interaction, embed=page)

    @admin_group.command(name="job-add", description="Cria um emprego na economia.")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_guild=True)
    async def job_add(self, interaction: discord.Interaction, key: str, name: str, salary: app_commands.Range[float, 0.01, MAX_ADMIN_AMOUNT], xp_reward: app_commands.Range[int, 1, 100000] = 25) -> None:
        key = key.strip().casefold()
        name = " ".join(name.split())
        if not re.fullmatch(r"[a-z0-9_-]{2,32}", key):
            await respond(interaction, "A chave deve ter 2 a 32 caracteres usando apenas a-z, 0-9, _ ou -.", ephemeral=True)
            return
        if not name or len(name) > 100 or not self.valid_amount(salary):
            await respond(interaction, "Nome e salário precisam respeitar os limites do emprego.", ephemeral=True)
            return
        guild = interaction.guild
        assert guild is not None
        await defer(interaction)
        async with session_factory() as session:
            duplicate = await session.scalar(select(Job.id).where(Job.guild_id == guild.id, Job.key == key).limit(1))
            if duplicate is not None:
                await respond(interaction, "Já existe um emprego com essa chave.", ephemeral=True)
                return
            row = Job(guild_id=guild.id, key=key, name=name, salary=Decimal(str(salary)), xp_reward=xp_reward, requirements={}, created_at=utc_now(), updated_at=utc_now())
            session.add(row)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                await respond(interaction, "O emprego não pôde ser criado porque a chave já existe.", ephemeral=True)
                return
            job_id = row.id
        await self.audit(guild.id, interaction.user.id, "job.create", f"job:{job_id}", None, {"key": key, "salary": str(salary), "xp_reward": xp_reward})
        page = embed("BN / EMPREGO CRIADO", f"**{name}** está disponível para os membros.", "admin")
        page.add_field(name="Chave", value=f"`{key}`", inline=True)
        page.add_field(name="Salário", value=money(salary), inline=True)
        page.add_field(name="XP", value=f"`{xp_reward}`", inline=True)
        await respond(interaction, embed=page)

    @admin_group.command(name="timezone", description="Configura o timezone do servidor.")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_guild=True)
    async def timezone(self, interaction: discord.Interaction, timezone_name: str) -> None:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
        timezone_name = timezone_name.strip()
        try:
            ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            await respond(interaction, "Timezone IANA inválido.", ephemeral=True)
            return
        guild = interaction.guild
        assert guild is not None
        await defer(interaction)
        async with session_factory() as session:
            settings = await session.get(GuildSettings, guild.id)
            if settings is None:
                now = utc_now()
                settings = GuildSettings(guild_id=guild.id, timezone=timezone_name, locale="pt-BR", created_at=now, updated_at=now)
                session.add(settings)
            else:
                settings.timezone = timezone_name
                settings.updated_at = utc_now()
            await session.commit()
        await self.audit(guild.id, interaction.user.id, "guild.timezone", "settings", None, {"timezone": timezone_name})
        page = embed("BN / TIMEZONE", f"O servidor agora usa `{timezone_name}`.", "admin")
        page.add_field(name="Timezone", value=f"`{timezone_name}`", inline=False)
        await respond(interaction, embed=page)


def add_to_tree(bot: commands.Bot) -> None:
    bot.tree.add_command(admin_group)
