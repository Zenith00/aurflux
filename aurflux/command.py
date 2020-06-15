from __future__ import annotations
from . import ext

import typing as ty
import functools as fnt

if ty.TYPE_CHECKING:
    import discord
    from .context import Context
    from ._types import *
    from .errors import *
    from .aurflux import Aurflux
    from . import argh
    from .config import Config

import typing as ty
import itertools as itt
import asyncio as aio
import inspect
from .context import MessageContext

import dataclasses


def _coroify(func):  # todo: move to aurcore
    if aio.iscoroutinefunction(func):
        return func
    fnt.wraps(func)

    async def __async_wrapper(*args, **kwargs):
        func(*args, **kwargs)

    return __async_wrapper


@ext.AutoRepr
class Command:

    def __init__(
            self,
            client: Aurflux,
            func: ty.Callable[..., ty.Awaitable],
            name: str,
            parsed: bool,
            private: bool = False,
            generator: bool = False

    ):
        self.func = func
        self.client = client
        self.name = name
        self.doc = inspect.getdoc(func)
        self.parsed = parsed
        self.checks: ty.List[ty.Callable[[MessageContext], ty.Awaitable[bool]]] = []
        self.builtin = False
        self.argparser: ty.Optional[argh.ArgumentParser] = None
        self.private = private
        func_doc = inspect.getdoc(self.func)
        if not func_doc:
            if not (private or self.parsed):
                raise RuntimeError(f"{self.func} lacks a docstring!")
        else:
            self.short_usage = func_doc.split("\n")[0]
            self.long_usage = func_doc[func_doc.index("\n"):func_doc.rindex(":param")]

    def execute(self, ctx: MessageContext):
        configs = self.client.CONFIG.of(ctx)
        ctx.command = self
        if (self.argparser is not None) ^ self.parsed:
            raise RuntimeError(f"Parsed command {self} has not been decorated with Argh")

        if ctx.author.id != self.client.admin_id:
            aio.gather(*[_coroify(check)(ctx) for check in self.checks])

        args: str = ctx.message.content.removeprefix(configs["prefix"]).removeprefix(self.name).lstrip()

        if self.parsed:
            assert self.argparser is not None  # typing
            return self.func(ctx, **self.argparser.parse_args(args.split(" ") if args else []).__dict__)
        else:
            # if inspect.isasyncgenfunction(self.func):
            #     return self.func(ctx, args)
            return self.func(ctx, args)


class CommandCheck:
    CheckPredicate: ty.TypeAlias = ty.Callable[[MessageContext], ty.Awaitable[bool]]
    CommandTransformDeco: ty.TypeAlias = ty.Callable[[Command], Command]

    @staticmethod
    def check(*predicates: CheckPredicate) -> CommandTransformDeco:
        def add_checks_deco(command: Command) -> Command:
            command.checks.extend(predicates)
            return command

        return add_checks_deco

    @staticmethod
    def or_(*predicates: CheckPredicate) -> CheckPredicate:
        async def orred_predicate(ctx: MessageContext) -> bool:
            return any(await predicate(ctx) for predicate in predicates)

        return orred_predicate

    @staticmethod
    def and_(*predicates: CheckPredicate) -> CheckPredicate:
        async def anded_predicate(ctx: MessageContext) -> bool:
            return all(await predicate(ctx) for predicate in predicates)

        return anded_predicate

    @staticmethod
    def whitelist() -> CheckPredicate:
        async def whitelist_predicate(ctx: MessageContext) -> bool:
            if ctx.config is None:
                raise RuntimeError(f"Config has not been initialized for ctx {ctx} in cmd {Command}")
            if not any(identifier in ctx.config["whitelist"] for identifier in ctx.auth_identifiers):
                raise NotWhitelisted()
            return True

        return whitelist_predicate

    @staticmethod
    def has_permissions(
            required_perms: discord.Permissions
    ) -> CheckPredicate:
        async def perm_predicate(ctx):
            ctx_perms: discord.Permissions = ctx.channel.permissions_for(ctx.author)

            missing = [perm for perm, value in required_perms if getattr(ctx_perms, perm) != value]

            if not missing:
                return True

            raise UserMissingPermissions(missing)

        return perm_predicate

    @staticmethod
    def bot_has_permissions(
            required_perms: discord.Permissions
    ) -> CheckPredicate:

        async def perm_predicate(ctx: MessageContext):
            ctx_perms: discord.Permissions = ctx.channel.permissions_for(ctx.guild.me)

            missing = [perm for perm, value in required_perms if getattr(ctx_perms, perm) != value]

            if not missing:
                return True

            raise BotMissingPermissions(missing)

        return perm_predicate
