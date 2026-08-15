"""Discord UI components.

Two flows live here:
  - RevealRoleView: fallback for players whose DMs are closed. Discord
    won't let us push an unprompted ephemeral message, but a button click
    IS a fresh interaction from that exact user, so we can attach the
    ephemeral reveal to that.
  - ShootSelectView / ShootConfirmView: the Officer's /shoot flow. Selecting
    a suspect doesn't fire immediately - it swaps to a Confirm/Cancel step,
    because a misclick on a plain button has no undo and ends the game.

Both timed views track a reference to their own message and override
on_timeout() to grey themselves out with an explanatory line instead of
silently going dead - a stale-looking but still-clickable button is the
kind of rough edge that makes a UI feel unfinished.
"""

from __future__ import annotations

from typing import Awaitable, Callable, Optional

import discord


class RevealRoleView(discord.ui.View):
    def __init__(self, target_id: int, embed: discord.Embed, *, timeout: Optional[float] = None):
        super().__init__(timeout=timeout)
        self.target_id = target_id
        self.embed = embed

    @discord.ui.button(label="Reveal my role", style=discord.ButtonStyle.primary, emoji="\U0001F50D")
    async def reveal(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.target_id:
            await interaction.response.send_message("This button isn't for you.", ephemeral=True)
            return
        await interaction.response.send_message(embed=self.embed, ephemeral=True)


ResolveCallback = Callable[[int], Awaitable[None]]


class ShootConfirmView(discord.ui.View):
    def __init__(self, resolve_callback: ResolveCallback, target_id: int,
                 target_display: str, *, timeout: float = 60.0):
        super().__init__(timeout=timeout)
        self.resolve_callback = resolve_callback
        self.target_id = target_id
        self.target_display = target_display
        self.message: Optional[discord.Message] = None

    @discord.ui.button(label="Confirm Shot", style=discord.ButtonStyle.danger, emoji="\U0001F52B")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        for child in self.children:
            child.disabled = True
        self.stop()
        await interaction.response.edit_message(
            content=f"\U0001F52B Shot fired at **{self.target_display}**. Resolving...",
            view=self,
        )
        await self.resolve_callback(self.target_id)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, emoji="\u21A9\uFE0F")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.stop()
        await interaction.response.edit_message(
            content="Cancelled - run `/shoot` again anytime before time runs out.",
            view=None,
        )

    async def on_timeout(self) -> None:
        for child in self.children:
            child.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(
                    content="\u231B That suspect timed out unconfirmed - run `/shoot` again anytime.",
                    view=self,
                )
            except discord.HTTPException:
                pass


class ShootSelect(discord.ui.Select):
    def __init__(self, options: list[discord.SelectOption], resolve_callback: ResolveCallback):
        super().__init__(placeholder="\U0001F50E Select a suspect...", min_values=1, max_values=1, options=options)
        self.resolve_callback = resolve_callback

    async def callback(self, interaction: discord.Interaction) -> None:
        target_id = int(self.values[0])
        target_display = next(o.label for o in self.options if o.value == self.values[0])
        confirm_view = ShootConfirmView(self.resolve_callback, target_id, target_display)
        await interaction.response.edit_message(
            content=f"\U0001F52B Shoot **{target_display}**? This ends the round immediately - no undo.",
            view=confirm_view,
        )
        confirm_view.message = await interaction.original_response()


class ShootSelectView(discord.ui.View):
    def __init__(self, options: list[discord.SelectOption], resolve_callback: ResolveCallback,
                 *, timeout: float = 120.0):
        super().__init__(timeout=timeout)
        self.message: Optional[discord.Message] = None
        self.add_item(ShootSelect(options, resolve_callback))

    async def on_timeout(self) -> None:
        for child in self.children:
            child.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(
                    content="\u231B That suspect list timed out - run `/shoot` again anytime.",
                    view=self,
                )
            except discord.HTTPException:
                pass


class HunchSelect(discord.ui.Select):
    """Unlike ShootSelect, this has no confirm step and doesn't disable
    itself after one pick - a Vigilante's hunch is low-stakes and openly
    documented as changeable ("pick again anytime"), so the same dropdown
    stays live and just re-locks the hunch on every selection."""

    def __init__(self, options: list[discord.SelectOption], lock_callback: ResolveCallback):
        super().__init__(placeholder="\U0001F3AF Lock in your hunch...", min_values=1, max_values=1, options=options)
        self.lock_callback = lock_callback

    async def callback(self, interaction: discord.Interaction) -> None:
        target_id = int(self.values[0])
        target_display = next(o.label for o in self.options if o.value == self.values[0])
        await self.lock_callback(target_id)
        await interaction.response.edit_message(
            content=(
                f"\U0001F3AF Hunch locked in: **{target_display}**. This is just "
                "between you and the case file - it won't affect the round. Pick "
                "again anytime before time's up to change it."
            ),
            view=self.view,
        )


class HunchSelectView(discord.ui.View):
    def __init__(self, options: list[discord.SelectOption], lock_callback: ResolveCallback,
                 *, timeout: float = 120.0):
        super().__init__(timeout=timeout)
        self.message: Optional[discord.Message] = None
        self.add_item(HunchSelect(options, lock_callback))

    async def on_timeout(self) -> None:
        for child in self.children:
            child.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(
                    content="\u231B That hunch picker timed out - run `/hunch` again anytime before the round ends.",
                    view=self,
                )
            except discord.HTTPException:
                pass
