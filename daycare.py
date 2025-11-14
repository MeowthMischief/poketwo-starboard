import discord
from discord.ext import commands
import re
import asyncio
from datetime import datetime, timezone
from database import db
from config import EMBED_COLOR
from typing import Optional, List, Dict
import math


class Daycare(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # PokéTwo bot ID and alternative mention format
        self.POKETWO_ID = 716390085896962058
        self.POKETWO_MENTION = "@Pokétwo#8236"

    def extract_poketwo_commands(self, content: str) -> List[str]:
        """Extract PokéTwo dc add commands from message content"""
        commands = []
        lines = content.split('\n')

        for line in lines:
            line = line.strip()

            # Remove code blocks
            line = line.replace('```', '').strip()

            if not line:
                continue

            # Pattern for @mention format
            mention_pattern = rf"<@{self.POKETWO_ID}>\s+dc\s+add\s+(\d+)\s+(\d+)"
            # Pattern for @Pokétwo#8236 format  
            username_pattern = rf"{re.escape(self.POKETWO_MENTION)}\s+dc\s+add\s+(\d+)\s+(\d+)"

            mention_match = re.search(mention_pattern, line, re.IGNORECASE)
            username_match = re.search(username_pattern, line, re.IGNORECASE)

            if mention_match:
                num1, num2 = mention_match.groups()
                commands.append(f"<@{self.POKETWO_ID}> dc add {num1} {num2}")
            elif username_match:
                num1, num2 = username_match.groups()
                commands.append(f"<@{self.POKETWO_ID}> dc add {num1} {num2}")
            else:
                # Pattern for simple "number number" format (e.g., "1 2", "4 5")
                simple_pattern = r'^(\d+)\s+(\d+)$'
                simple_match = re.match(simple_pattern, line)

                if simple_match:
                    num1, num2 = simple_match.groups()
                    commands.append(f"<@{self.POKETWO_ID}> dc add {num1} {num2}")

        return commands

    class StoreConfirmationView(discord.ui.View):
        def __init__(self, user_id, dataset_name, commands):
            super().__init__(timeout=30)
            self.user_id = user_id
            self.dataset_name = dataset_name
            self.commands = commands

        @discord.ui.button(label="Yes, Update", style=discord.ButtonStyle.success, emoji="✅")
        async def confirm_update(self, interaction: discord.Interaction, button: discord.ui.Button):
            if interaction.user.id != self.user_id:
                await interaction.response.send_message("❌ This is not your confirmation dialog.", ephemeral=True)
                return

            try:
                dataset_name_lower = self.dataset_name.lower()
                current_time = datetime.now(timezone.utc)

                # Get existing dataset to preserve creation time
                existing = await db.db.datasets.find_one({"user_id": self.user_id, "name_lower": dataset_name_lower})

                dataset_doc = {
                    "user_id": self.user_id,
                    "name": self.dataset_name,
                    "name_lower": dataset_name_lower,
                    "commands": self.commands,
                    "created_at": existing["created_at"] if existing else current_time,
                    "last_modified": current_time,
                    "last_used": existing.get("last_used") if existing else None
                }

                await db.db.datasets.replace_one(
                    {"user_id": self.user_id, "name_lower": dataset_name_lower},
                    dataset_doc,
                    upsert=True
                )

                embed = discord.Embed(
                    title="✅ Dataset Updated",
                    description=f"Dataset **{self.dataset_name}** has been updated with {len(self.commands)} command(s).",
                    color=EMBED_COLOR
                )

                # Disable all buttons
                for item in self.children:
                    item.disabled = True

                await interaction.response.edit_message(embed=embed, view=self)

            except Exception as e:
                embed = discord.Embed(
                    title="❌ Error",
                    description=f"Error updating dataset: {e}",
                    color=EMBED_COLOR
                )
                await interaction.response.edit_message(embed=embed, view=None)

        @discord.ui.button(label="No, Cancel", style=discord.ButtonStyle.danger, emoji="❌")
        async def cancel_update(self, interaction: discord.Interaction, button: discord.ui.Button):
            if interaction.user.id != self.user_id:
                await interaction.response.send_message("❌ This is not your confirmation dialog.", ephemeral=True)
                return

            embed = discord.Embed(
                title="❌ Update Cancelled",
                description="Dataset update has been cancelled.",
                color=EMBED_COLOR
            )

            # Disable all buttons
            for item in self.children:
                item.disabled = True

            await interaction.response.edit_message(embed=embed, view=self)

        async def on_timeout(self):
            # Disable all buttons when timeout occurs
            for item in self.children:
                item.disabled = True

    @commands.command(name='store')
    async def store_command(self, ctx, *, dataset_name: str):
        """Store PokéTwo command data from replied message with a custom name"""
        if not ctx.message.reference:
            embed = discord.Embed(
                description="❌ Please use this command as a reply to a message containing PokéTwo commands.\n**Usage:** `?store <dataset_name>`",
                color=EMBED_COLOR
            )
            await ctx.reply(embed=embed, mention_author=False)
            return

        if not dataset_name.strip():
            embed = discord.Embed(
                description="❌ Please provide a name for the dataset.\n**Usage:** `?store <dataset_name>`",
                color=EMBED_COLOR
            )
            await ctx.reply(embed=embed, mention_author=False)
            return

        dataset_name = dataset_name.strip()
        dataset_name_lower = dataset_name.lower()
        user_id = ctx.author.id

        try:
            referenced_message = await ctx.channel.fetch_message(ctx.message.reference.message_id)
            message_content = referenced_message.content

            commands = self.extract_poketwo_commands(message_content)

            if not commands:
                embed = discord.Embed(
                    description="❌ No valid PokéTwo 'dc add' commands found in the referenced message.",
                    color=EMBED_COLOR
                )
                await ctx.reply(embed=embed, mention_author=False)
                return

            # Check if dataset with this name already exists for this user (case insensitive)
            existing = await db.db.datasets.find_one({"user_id": user_id, "name_lower": dataset_name_lower})

            if existing:
                # Show confirmation dialog
                embed = discord.Embed(
                    title="⚠️ Dataset Already Exists",
                    description=f"Dataset **{dataset_name}** already exists with {len(existing.get('commands', []))} command(s).\n\nDo you want to update it with {len(commands)} new command(s)?",
                    color=0xffaa00
                )

                view = self.StoreConfirmationView(user_id, dataset_name, commands)
                await ctx.reply(embed=embed, view=view, mention_author=False)
                return

            # Create new dataset
            current_time = datetime.now(timezone.utc)

            dataset_doc = {
                "user_id": user_id,
                "name": dataset_name,
                "name_lower": dataset_name_lower,
                "commands": commands,
                "created_at": current_time,
                "last_modified": current_time,
                "last_used": None
            }

            await db.db.datasets.insert_one(dataset_doc)

            embed = discord.Embed(
                description=f"✅ Stored dataset **{dataset_name}** with {len(commands)} command(s).",
                color=EMBED_COLOR
            )
            await ctx.reply(embed=embed, mention_author=False)

        except discord.NotFound:
            embed = discord.Embed(
                description="❌ Could not find the referenced message.",
                color=EMBED_COLOR
            )
            await ctx.reply(embed=embed, mention_author=False)
        except Exception as e:
            embed = discord.Embed(
                description=f"❌ Error storing data: {e}",
                color=EMBED_COLOR
            )
            await ctx.reply(embed=embed, mention_author=False)
            print(f"Store command error: {e}")

    class DatasetSelectView(discord.ui.View):
        def __init__(self, datasets, user_id, current_page=0):
            super().__init__(timeout=60)
            self.datasets = datasets
            self.user_id = user_id
            self.current_page = current_page
            self.items_per_page = 20
            self.total_pages = math.ceil(len(datasets) / self.items_per_page)

            # Add select menu
            self.add_select_menu()

            # Add navigation buttons if needed
            if self.total_pages > 1:
                self.add_navigation_buttons()

        def add_select_menu(self):
            start_idx = self.current_page * self.items_per_page
            end_idx = min(start_idx + self.items_per_page, len(self.datasets))
            page_datasets = self.datasets[start_idx:end_idx]

            options = [
                discord.SelectOption(
                    label=dataset["name"],
                    description=f"{len(dataset.get('commands', []))} commands",
                    value=dataset["name"]
                )
                for dataset in page_datasets
            ]

            if options:
                select = discord.ui.Select(
                    placeholder=f"Choose a dataset (Page {self.current_page + 1}/{self.total_pages})...",
                    options=options
                )
                select.callback = self.select_callback
                self.add_item(select)

        def add_navigation_buttons(self):
            # Previous button
            prev_button = discord.ui.Button(
                label="◀ Previous", 
                style=discord.ButtonStyle.secondary,
                disabled=self.current_page == 0
            )
            prev_button.callback = self.previous_page
            self.add_item(prev_button)

            # Page indicator
            page_info = discord.ui.Button(
                label=f"Page {self.current_page + 1}/{self.total_pages}",
                style=discord.ButtonStyle.secondary,
                disabled=True
            )
            self.add_item(page_info)

            # Next button
            next_button = discord.ui.Button(
                label="Next ▶", 
                style=discord.ButtonStyle.secondary,
                disabled=self.current_page >= self.total_pages - 1
            )
            next_button.callback = self.next_page
            self.add_item(next_button)

        async def select_callback(self, interaction):
            if interaction.user.id != self.user_id:
                await interaction.response.send_message("❌ This is not your selection menu.", ephemeral=True)
                return

            selected_name = interaction.data['values'][0]
            selected_name_lower = selected_name.lower()

            # Update user state
            current_time = datetime.now(timezone.utc)
            await db.db.user_states.replace_one(
                {"user_id": self.user_id},
                {
                    "user_id": self.user_id,
                    "selected_dataset": selected_name,
                    "selected_dataset_lower": selected_name_lower,
                    "current_position": 0,
                    "last_updated": current_time
                },
                upsert=True
            )

            # Update last_used for the dataset
            await db.db.datasets.update_one(
                {"user_id": self.user_id, "name_lower": selected_name_lower},
                {"$set": {"last_used": current_time}}
            )

            await interaction.response.send_message(f"✅ Selected dataset: **{selected_name}**", ephemeral=True)

        async def previous_page(self, interaction):
            if interaction.user.id != self.user_id:
                await interaction.response.send_message("❌ This is not your selection menu.", ephemeral=True)
                return

            self.current_page = max(0, self.current_page - 1)
            new_view = Daycare.DatasetSelectView(self.datasets, self.user_id, self.current_page)
            await interaction.response.edit_message(content="📋 Select a dataset to work with:", view=new_view)

        async def next_page(self, interaction):
            if interaction.user.id != self.user_id:
                await interaction.response.send_message("❌ This is not your selection menu.", ephemeral=True)
                return

            self.current_page = min(self.total_pages - 1, self.current_page + 1)
            new_view = Daycare.DatasetSelectView(self.datasets, self.user_id, self.current_page)
            await interaction.response.edit_message(content="📋 Select a dataset to work with:", view=new_view)

    class ListPaginationView(discord.ui.View):
        def __init__(self, datasets, user_id, selected_dataset, current_page=0):
            super().__init__(timeout=60)
            self.datasets = datasets
            self.user_id = user_id
            self.selected_dataset = selected_dataset
            self.current_page = current_page
            self.items_per_page = 24  # Leave room for footer
            self.total_pages = math.ceil(len(datasets) / self.items_per_page)

            # Add navigation buttons if needed
            if self.total_pages > 1:
                self.add_navigation_buttons()

        def add_navigation_buttons(self):
            # Previous button
            prev_button = discord.ui.Button(
                label="◀ Previous", 
                style=discord.ButtonStyle.secondary,
                disabled=self.current_page == 0
            )
            prev_button.callback = self.previous_page
            self.add_item(prev_button)

            # Page indicator
            page_info = discord.ui.Button(
                label=f"Page {self.current_page + 1}/{self.total_pages}",
                style=discord.ButtonStyle.secondary,
                disabled=True
            )
            self.add_item(page_info)

            # Next button
            next_button = discord.ui.Button(
                label="Next ▶", 
                style=discord.ButtonStyle.secondary,
                disabled=self.current_page >= self.total_pages - 1
            )
            next_button.callback = self.next_page
            self.add_item(next_button)

        def create_embed(self):
            start_idx = self.current_page * self.items_per_page
            end_idx = min(start_idx + self.items_per_page, len(self.datasets))
            page_datasets = self.datasets[start_idx:end_idx]

            embed = discord.Embed(
                title=f"📋 Your Datasets (Page {self.current_page + 1}/{self.total_pages})",
                color=EMBED_COLOR
            )

            for dataset in page_datasets:
                name = dataset["name"]
                name_lower = dataset["name_lower"]
                command_count = len(dataset.get("commands", []))
                last_used = dataset.get("last_used")

                status = "<:green_dot:1391644125496873010> Selected" if name_lower == self.selected_dataset else "<:dark:1391644039576682516>"
                last_used_str = f"<t:{int(last_used.timestamp())}:R>" if last_used else "Never"

                embed.add_field(
                    name=f"{status} {name}",
                    value=f"Commands: {command_count}\nLast used: {last_used_str}",
                    inline=True
                )

            embed.set_footer(text=f"Total datasets: {len(self.datasets)} | Showing {start_idx + 1}-{end_idx}")
            return embed

        async def previous_page(self, interaction):
            if interaction.user.id != self.user_id:
                await interaction.response.send_message("❌ This is not your list.", ephemeral=True)
                return

            self.current_page = max(0, self.current_page - 1)
            new_view = Daycare.ListPaginationView(
                self.datasets, 
                self.user_id, 
                self.selected_dataset, 
                self.current_page
            )
            await interaction.response.edit_message(embed=new_view.create_embed(), view=new_view)

        async def next_page(self, interaction):
            if interaction.user.id != self.user_id:
                await interaction.response.send_message("❌ This is not your list.", ephemeral=True)
                return

            self.current_page = min(self.total_pages - 1, self.current_page + 1)
            new_view = Daycare.ListPaginationView(
                self.datasets, 
                self.user_id, 
                self.selected_dataset, 
                self.current_page
            )
            await interaction.response.edit_message(embed=new_view.create_embed(), view=new_view)

        async def on_timeout(self):
            # Disable all buttons when timeout occurs
            for item in self.children:
                item.disabled = True

    @commands.command(name='list')
    async def list_command(self, ctx):
        """List all datasets for the user"""
        user_id = ctx.author.id

        try:
            datasets = await db.db.datasets.find({"user_id": user_id}).to_list(length=None)

            if not datasets:
                embed = discord.Embed(
                    title="📋 Your Datasets",
                    description="You have no stored datasets. Use `?store <name>` to create one.",
                    color=EMBED_COLOR
                )
                await ctx.reply(embed=embed, mention_author=False)
                return

            # Get user state for current selection
            user_state = await db.db.user_states.find_one({"user_id": user_id})
            selected_dataset = user_state.get("selected_dataset", "").lower() if user_state else None

            # Create pagination view
            view = self.ListPaginationView(datasets, user_id, selected_dataset)
            embed = view.create_embed()

            await ctx.reply(embed=embed, view=view if view.total_pages > 1 else None, mention_author=False)

        except Exception as e:
            embed = discord.Embed(
                title="❌ Error",
                description=f"Error listing datasets: {e}",
                color=EMBED_COLOR
            )
            await ctx.reply(embed=embed, mention_author=False)
            print(f"List command error: {e}")

    @commands.hybrid_command(name="select", description="Select a dataset to work with")
    async def select_command(self, ctx, *, dataset_name: str = None):
        """Select a dataset from dropdown menu with pagination or by name"""
        user_id = ctx.author.id

        try:
            # Get all datasets for this user
            datasets = await db.db.datasets.find({"user_id": user_id}).to_list(length=None)

            if not datasets:
                embed = discord.Embed(
                    title="❌ No Datasets Found",
                    description="You have no stored datasets. Use `?store <name>` to create one.",
                    color=EMBED_COLOR
                )
                await ctx.reply(embed=embed, mention_author=False)
                return

            # If dataset_name is provided, try to select it directly
            if dataset_name:
                dataset_name = dataset_name.strip()
                dataset_name_lower = dataset_name.lower()

                # Find the dataset (case insensitive)
                selected_dataset = next((d for d in datasets if d["name_lower"] == dataset_name_lower), None)

                if not selected_dataset:
                    embed = discord.Embed(
                        title="❌ Dataset Not Found",
                        description=f"Could not find dataset **{dataset_name}**.",
                        color=EMBED_COLOR
                    )
                    await ctx.reply(embed=embed, mention_author=False)
                    return

                # Update user state
                current_time = datetime.now(timezone.utc)
                await db.db.user_states.replace_one(
                    {"user_id": user_id},
                    {
                        "user_id": user_id,
                        "selected_dataset": selected_dataset["name"],
                        "selected_dataset_lower": selected_dataset["name_lower"],
                        "current_position": 0,
                        "last_updated": current_time
                    },
                    upsert=True
                )

                # Update last_used for the dataset
                await db.db.datasets.update_one(
                    {"user_id": user_id, "name_lower": dataset_name_lower},
                    {"$set": {"last_used": current_time}}
                )

                embed = discord.Embed(
                    title="✅ Dataset Selected",
                    description=f"Selected dataset: **{selected_dataset['name']}**",
                    color=EMBED_COLOR
                )
                await ctx.reply(embed=embed, mention_author=False)
                return

            # If no dataset_name provided, show dropdown menu
            view = self.DatasetSelectView(datasets, user_id)
            await ctx.reply("📋 Select a dataset to work with:", view=view, mention_author=False)

        except Exception as e:
            embed = discord.Embed(
                title="❌ Error",
                description=f"Error loading datasets: {e}",
                color=EMBED_COLOR
            )
            await ctx.reply(embed=embed, mention_author=False)
            print(f"Select command error: {e}")

    @commands.hybrid_command(name="next", description="Get the next command from selected dataset")
    async def next_command(self, ctx):
        """Show the next stored entry in sequence from selected dataset"""
        user_id = ctx.author.id

        try:
            # Get user state
            user_state = await db.db.user_states.find_one({"user_id": user_id})

            if not user_state or not user_state.get("selected_dataset"):
                embed = discord.Embed(
                    title="❌ No Dataset Selected",
                    description="No dataset selected. Use `/select` to choose a dataset first.",
                    color=EMBED_COLOR
                )
                await ctx.reply(embed=embed, mention_author=False)
                return

            dataset_name = user_state["selected_dataset"]
            dataset_name_lower = user_state.get("selected_dataset_lower", dataset_name.lower())
            current_pos = user_state.get("current_position", 0)

            # Get the dataset
            dataset = await db.db.datasets.find_one({"user_id": user_id, "name_lower": dataset_name_lower})

            if not dataset:
                embed = discord.Embed(
                    title="❌ Dataset Not Found",
                    description=f"Dataset **{dataset_name}** not found.",
                    color=EMBED_COLOR
                )
                await ctx.reply(embed=embed, mention_author=False)
                return

            commands = dataset.get("commands", [])

            if current_pos >= len(commands):
                embed = discord.Embed(
                    title="❌ No More Commands",
                    description=f"No more commands available in dataset **{dataset_name}**.",
                    color=EMBED_COLOR
                )
                await ctx.reply(embed=embed, mention_author=False)
                return

            # Get current command (BEFORE incrementing position)
            command = commands[current_pos]

            # Calculate new position for next time
            new_position = current_pos + 1

            # Update position
            await db.db.user_states.update_one(
                {"user_id": user_id},
                {"$set": {"current_position": new_position}}
            )

            # Update last used
            current_time = datetime.now(timezone.utc)
            await db.db.datasets.update_one(
                {"user_id": user_id, "name_lower": dataset_name_lower},
                {"$set": {"last_used": current_time}}
            )

            embed = discord.Embed(
                title=f"📝 Next Command from **{dataset_name}**",
                description=f"**Entry {current_pos + 1}/{len(commands)}**\n```{command}```",
                color=EMBED_COLOR
            )
            # FIXED: Show position correctly (was showing same position twice)
            embed.set_footer(text=f"Position advanced to {new_position}/{len(commands)}")

            await ctx.reply(embed=embed, mention_author=False)

        except Exception as e:
            embed = discord.Embed(
                title="❌ Error",
                description=f"Error retrieving next command: {e}",
                color=EMBED_COLOR
            )
            await ctx.reply(embed=embed, mention_author=False)
            print(f"Next command error: {e}")

    @commands.hybrid_command(name="jump", description="Jump to a specific entry number")
    async def jump_command(self, ctx, entry_number: int):
        """Jump to a specific entry number in the selected dataset"""
        user_id = ctx.author.id

        try:
            # Get user state
            user_state = await db.db.user_states.find_one({"user_id": user_id})

            if not user_state or not user_state.get("selected_dataset"):
                embed = discord.Embed(
                    title="❌ No Dataset Selected",
                    description="No dataset selected. Use `/select` to choose a dataset first.",
                    color=EMBED_COLOR
                )
                await ctx.reply(embed=embed, mention_author=False)
                return

            dataset_name = user_state["selected_dataset"]
            dataset_name_lower = user_state.get("selected_dataset_lower", dataset_name.lower())
            old_position = user_state.get("current_position", 0)

            # Get the dataset
            dataset = await db.db.datasets.find_one({"user_id": user_id, "name_lower": dataset_name_lower})

            if not dataset:
                embed = discord.Embed(
                    title="❌ Dataset Not Found",
                    description=f"Dataset **{dataset_name}** not found.",
                    color=EMBED_COLOR
                )
                await ctx.reply(embed=embed, mention_author=False)
                return

            commands = dataset.get("commands", [])

            if entry_number < 1 or entry_number > len(commands):
                embed = discord.Embed(
                    title="❌ Invalid Entry Number",
                    description=f"Please choose between 1 and {len(commands)}.",
                    color=EMBED_COLOR
                )
                await ctx.reply(embed=embed, mention_author=False)
                return

            # Update position to the entry number (so next /next will get entry_number + 1)
            new_position = entry_number
            await db.db.user_states.update_one(
                {"user_id": user_id},
                {"$set": {"current_position": new_position}}
            )

            # Get the requested command (entry_number - 1 because arrays are 0-indexed)
            command = commands[entry_number - 1]

            # Update last used
            current_time = datetime.now(timezone.utc)
            await db.db.datasets.update_one(
                {"user_id": user_id, "name_lower": dataset_name_lower},
                {"$set": {"last_used": current_time}}
            )

            embed = discord.Embed(
                title=f"🎯 Jumped to Entry in **{dataset_name}**",
                description=f"**Entry {entry_number}/{len(commands)}**\n```{command}```",
                color=EMBED_COLOR
            )
            embed.set_footer(text=f"Position set to {new_position}/{len(commands)}")

            await ctx.reply(embed=embed, mention_author=False)

        except Exception as e:
            embed = discord.Embed(
                title="❌ Error",
                description=f"Error jumping to entry: {e}",
                color=EMBED_COLOR
            )
            await ctx.reply(embed=embed, mention_author=False)
            print(f"Jump command error: {e}")

    @commands.hybrid_command(name="current", description="Show current position and dataset info")
    async def current_command(self, ctx):
        """Show current position and dataset information"""
        user_id = ctx.author.id

        try:
            # Get user state
            user_state = await db.db.user_states.find_one({"user_id": user_id})

            if not user_state or not user_state.get("selected_dataset"):
                embed = discord.Embed(
                    title="📍 Current Status",
                    description="No dataset currently selected. Use `/select` to choose one.",
                    color=EMBED_COLOR
                )
                await ctx.reply(embed=embed, mention_author=False)
                return

            dataset_name = user_state["selected_dataset"]
            dataset_name_lower = user_state.get("selected_dataset_lower", dataset_name.lower())
            current_pos = user_state.get("current_position", 0)

            # Get the dataset
            dataset = await db.db.datasets.find_one({"user_id": user_id, "name_lower": dataset_name_lower})

            if not dataset:
                embed = discord.Embed(
                    title="❌ Dataset Not Found",
                    description=f"Selected dataset **{dataset_name}** no longer exists.",
                    color=EMBED_COLOR
                )
                await ctx.reply(embed=embed, mention_author=False)
                return

            commands = dataset.get("commands", [])

            embed = discord.Embed(
                title=f"📍 Current Status: **{dataset_name}**",
                color=EMBED_COLOR
            )

            # Current position info
            if current_pos < len(commands):
                current_command = commands[current_pos]
                embed.add_field(
                    name="🎯 Current Position", 
                    value=f"Entry {current_pos + 1}/{len(commands)}", 
                    inline=True
                )
                embed.add_field(
                    name="📝 Next Command", 
                    value=f"```{current_command}```", 
                    inline=False
                )
            else:
                embed.add_field(
                    name="🎯 Current Position", 
                    value=f"End of dataset ({len(commands)}/{len(commands)})", 
                    inline=True
                )
                embed.add_field(
                    name="📝 Status", 
                    value="All commands completed", 
                    inline=False
                )

            # Dataset info
            embed.add_field(name="📊 Total Commands", value=len(commands), inline=True)
            embed.add_field(name="📈 Remaining", value=max(0, len(commands) - current_pos), inline=True)

            # Last used
            last_used = dataset.get("last_used")
            if last_used:
                embed.add_field(name="🕐 Last Used", value=f"<t:{int(last_used.timestamp())}:R>", inline=True)

            embed.set_footer(text="Use /next to get the next command")

            await ctx.reply(embed=embed, mention_author=False)

        except Exception as e:
            embed = discord.Embed(
                title="❌ Error",
                description=f"Error retrieving current status: {e}",
                color=EMBED_COLOR
            )
            await ctx.reply(embed=embed, mention_author=False)
            print(f"Current command error: {e}")

    @commands.command(name='ds')
    async def dataset_show_command(self, ctx, *, dataset_name: str):
        """Display the complete dataset content in the original stored format"""
        user_id = ctx.author.id
        dataset_name = dataset_name.strip()
        dataset_name_lower = dataset_name.lower()

        try:
            dataset = await db.db.datasets.find_one({"user_id": user_id, "name_lower": dataset_name_lower})
            if not dataset:
                embed = discord.Embed(
                    description=f"❌ Dataset **{dataset_name}** not found.",
                    color=EMBED_COLOR
                )
                await ctx.reply(embed=embed, mention_author=False)
                return

            commands = dataset.get("commands", [])

            if not commands:
                embed = discord.Embed(
                    description=f"📋 Dataset: **{dataset['name']}** is empty.",
                    color=EMBED_COLOR
                )
                await ctx.reply(embed=embed, mention_author=False)
                return

            # Format the commands in the original stored format
            formatted_content = f"**Dataset: {dataset['name']}** ({len(commands)} commands)\n\n"

            for i, command in enumerate(commands, 1):
                formatted_content += f"{i}) ```{command}```\n"

            # Check if content is too long for a single message
            if len(formatted_content) > 2000:
                # Split into multiple messages
                messages = []
                current_message = f"**Dataset: {dataset['name']}** ({len(commands)} commands)\n\n"

                for i, command in enumerate(commands, 1):
                    line = f"{i}) ```{command}```\n"

                    if len(current_message + line) > 2000:
                        messages.append(current_message)
                        current_message = line
                    else:
                        current_message += line

                if current_message:
                    messages.append(current_message)

                # Send first message as reply, others as regular messages
                await ctx.reply(messages[0], mention_author=False)
                for message in messages[1:]:
                    await ctx.send(message)
            else:
                # Send as single message
                await ctx.reply(formatted_content, mention_author=False)

        except Exception as e:
            embed = discord.Embed(
                description=f"❌ Error retrieving dataset: {e}",
                color=EMBED_COLOR
            )
            await ctx.reply(embed=embed, mention_author=False)
            print(f"Dataset show command error: {e}")

    @commands.command(name='del')
    async def delete_command(self, ctx, *, dataset_name: str):
        """Delete a dataset"""
        user_id = ctx.author.id
        dataset_name = dataset_name.strip()
        dataset_name_lower = dataset_name.lower()

        try:
            # Check if user has this dataset selected
            user_state = await db.db.user_states.find_one({"user_id": user_id})
            if user_state and user_state.get("selected_dataset", "").lower() == dataset_name_lower:
                embed = discord.Embed(
                    title="❌ Cannot Delete",
                    description=f"You cannot delete your currently selected dataset **{dataset_name}**. Please select a different dataset first.",
                    color=EMBED_COLOR
                )
                await ctx.reply(embed=embed, mention_author=False)
                return

            # Check if dataset exists (case insensitive)
            dataset = await db.db.datasets.find_one({"user_id": user_id, "name_lower": dataset_name_lower})
            if not dataset:
                embed = discord.Embed(
                    title="❌ Dataset Not Found",
                    description=f"Dataset **{dataset_name}** not found.",
                    color=EMBED_COLOR
                )
                await ctx.reply(embed=embed, mention_author=False)
                return

            # Delete the dataset
            await db.db.datasets.delete_one({"user_id": user_id, "name_lower": dataset_name_lower})

            embed = discord.Embed(
                title="✅ Dataset Deleted",
                description=f"Dataset **{dataset['name']}** has been deleted.",
                color=EMBED_COLOR
            )
            await ctx.reply(embed=embed, mention_author=False)

        except Exception as e:
            embed = discord.Embed(
                title="❌ Error",
                description=f"Error deleting dataset: {e}",
                color=EMBED_COLOR
            )
            await ctx.reply(embed=embed, mention_author=False)
            print(f"Delete command error: {e}")

    @commands.command(name='edit')
    async def edit_command(self, ctx, *, dataset_name: str):
        """Edit an existing dataset with new data from replied message"""
        if not ctx.message.reference:
            embed = discord.Embed(
                title="❌ No Message Referenced",
                description="Please use this command as a reply to a message containing new PokéTwo commands.\n**Usage:** `?edit <dataset_name>`",
                color=EMBED_COLOR
            )
            await ctx.reply(embed=embed, mention_author=False)
            return

        dataset_name = dataset_name.strip()
        dataset_name_lower = dataset_name.lower()
        user_id = ctx.author.id

        try:
            # Check if dataset exists (case insensitive)
            existing = await db.db.datasets.find_one({"user_id": user_id, "name_lower": dataset_name_lower})
            if not existing:
                embed = discord.Embed(
                    title="❌ Dataset Not Found",
                    description=f"Dataset **{dataset_name}** not found.",
                    color=EMBED_COLOR
                )
                await ctx.reply(embed=embed, mention_author=False)
                return

            referenced_message = await ctx.channel.fetch_message(ctx.message.reference.message_id)
            message_content = referenced_message.content

            commands = self.extract_poketwo_commands(message_content)

            if not commands:
                embed = discord.Embed(
                    title="❌ No Commands Found",
                    description="No valid PokéTwo 'dc add' commands found in the referenced message.",
                    color=EMBED_COLOR
                )
                await ctx.reply(embed=embed, mention_author=False)
                return

            # Update the dataset
            current_time = datetime.now(timezone.utc)
            await db.db.datasets.update_one(
                {"user_id": user_id, "name_lower": dataset_name_lower},
                {"$set": {
                    "commands": commands,
                    "last_modified": current_time
                }}
            )

            # Reset position if user has this dataset selected
            user_state = await db.db.user_states.find_one({"user_id": user_id})
            if user_state and user_state.get("selected_dataset", "").lower() == dataset_name_lower:
                await db.db.user_states.update_one(
                    {"user_id": user_id},
                    {"$set": {"current_position": 0}}
                )

            embed = discord.Embed(
                title="✅ Dataset Updated",
                description=f"Dataset **{existing['name']}** has been updated with {len(commands)} command(s).",
                color=EMBED_COLOR
            )
            await ctx.reply(embed=embed, mention_author=False)

        except discord.NotFound:
            embed = discord.Embed(
                title="❌ Message Not Found",
                description="Could not find the referenced message.",
                color=EMBED_COLOR
            )
            await ctx.reply(embed=embed, mention_author=False)
        except Exception as e:
            embed = discord.Embed(
                title="❌ Error",
                description=f"Error editing dataset: {e}",
                color=EMBED_COLOR
            )
            await ctx.reply(embed=embed, mention_author=False)
            print(f"Edit command error: {e}")

    @commands.command(name='rename')
    async def rename_command(self, ctx, *, args: str):
        """Rename a dataset using 'as' as divider - Usage: ?rename old_name as new_name"""
        user_id = ctx.author.id

        # Split by 'as' (case insensitive)
        parts = re.split(r'\s+as\s+', args.strip(), maxsplit=1, flags=re.IGNORECASE)

        if len(parts) != 2:
            embed = discord.Embed(
                title="❌ Invalid Format",
                description="Please use the format: `?rename old_name as new_name`\nExample: `?rename MEOW 4 as MEOW5`",
                color=EMBED_COLOR
            )
            await ctx.reply(embed=embed, mention_author=False)
            return

        old_name = parts[0].strip()
        new_name = parts[1].strip()

        if not old_name or not new_name:
            embed = discord.Embed(
                title="❌ Invalid Names",
                description="Both old and new names must be provided.\nExample: `?rename MEOW 4 as MEOW5`",
                color=EMBED_COLOR
            )
            await ctx.reply(embed=embed, mention_author=False)
            return

        old_name_lower = old_name.lower()
        new_name_lower = new_name.lower()

        try:
            # Check if old dataset exists (case insensitive)
            old_dataset = await db.db.datasets.find_one({"user_id": user_id, "name_lower": old_name_lower})
            if not old_dataset:
                embed = discord.Embed(
                    title="❌ Dataset Not Found",
                    description=f"Dataset **{old_name}** not found.",
                    color=EMBED_COLOR
                )
                await ctx.reply(embed=embed, mention_author=False)
                return

            # Check if new name already exists (case insensitive)
            existing_new = await db.db.datasets.find_one({"user_id": user_id, "name_lower": new_name_lower})
            if existing_new and existing_new["name_lower"] != old_name_lower:
                embed = discord.Embed(
                    title="❌ Name Already Exists",
                    description=f"A dataset with the name **{new_name}** already exists.",
                    color=EMBED_COLOR
                )
                await ctx.reply(embed=embed, mention_author=False)
                return

            # Update the dataset name
            current_time = datetime.now(timezone.utc)
            await db.db.datasets.update_one(
                {"user_id": user_id, "name_lower": old_name_lower},
                {"$set": {
                    "name": new_name,
                    "name_lower": new_name_lower,
                    "last_modified": current_time
                }}
            )

            # Update user state if this dataset is selected
            user_state = await db.db.user_states.find_one({"user_id": user_id})
            if user_state and user_state.get("selected_dataset", "").lower() == old_name_lower:
                await db.db.user_states.update_one(
                    {"user_id": user_id},
                    {"$set": {
                        "selected_dataset": new_name,
                        "selected_dataset_lower": new_name_lower
                    }}
                )

            embed = discord.Embed(
                title="✅ Dataset Renamed",
                description=f"Dataset **{old_dataset['name']}** has been renamed to **{new_name}**.",
                color=EMBED_COLOR
            )
            await ctx.reply(embed=embed, mention_author=False)

        except Exception as e:
            embed = discord.Embed(
                title="❌ Error",
                description=f"Error renaming dataset: {e}",
                color=EMBED_COLOR
            )
            await ctx.reply(embed=embed, mention_author=False)
            print(f"Rename command error: {e}")

    @commands.command(name='info')
    async def info_command(self, ctx, *, dataset_name: str):
        """Show information about a specific dataset"""
        user_id = ctx.author.id
        dataset_name = dataset_name.strip()
        dataset_name_lower = dataset_name.lower()

        try:
            dataset = await db.db.datasets.find_one({"user_id": user_id, "name_lower": dataset_name_lower})
            if not dataset:
                embed = discord.Embed(
                    title="❌ Dataset Not Found",
                    description=f"Dataset **{dataset_name}** not found.",
                    color=EMBED_COLOR
                )
                await ctx.reply(embed=embed, mention_author=False)
                return

            commands = dataset.get("commands", [])

            # Create info embed
            embed = discord.Embed(title=f"📊 Dataset Information: {dataset['name']}", color=EMBED_COLOR)

            # Basic info
            embed.add_field(name="📈 Commands Count", value=len(commands), inline=True)

            # Dates
            created_at = dataset.get("created_at")
            if created_at:
                embed.add_field(name="📅 Created", value=f"<t:{int(created_at.timestamp())}:R>", inline=True)

            last_modified = dataset.get("last_modified")
            if last_modified:
                embed.add_field(name="✏️ Last Modified", value=f"<t:{int(last_modified.timestamp())}:R>", inline=True)

            last_used = dataset.get("last_used")
            if last_used:
                embed.add_field(name="🕐 Last Used", value=f"<t:{int(last_used.timestamp())}:R>", inline=True)
            else:
                embed.add_field(name="🕐 Last Used", value="Never", inline=True)

            # Current selection status
            user_state = await db.db.user_states.find_one({"user_id": user_id})
            if user_state and user_state.get("selected_dataset", "").lower() == dataset_name_lower:
                current_pos = user_state.get("current_position", 0)
                embed.add_field(name="📍 Status", value=f"Currently selected\nPosition: {current_pos + 1}", inline=True)
            else:
                embed.add_field(name="📍 Status", value="Not selected", inline=True)

            # Add dataset content
            if commands:
                content_text = ""
                for i, command in enumerate(commands, 1):
                    content_text += f"{i}. {command}\n"

                # Split content if it's too long for Discord
                if len(content_text) > 1000:
                    content_text = content_text[:997] + "..."

                embed.add_field(
                    name="📝 Dataset Content",
                    value=f"```\n{content_text}```",
                    inline=False
                )
            else:
                embed.add_field(
                    name="📝 Dataset Content",
                    value="No commands found",
                    inline=False
                )

            embed.set_footer(text=f"Owner: {ctx.author.display_name}")
            await ctx.reply(embed=embed, mention_author=False)

        except Exception as e:
            embed = discord.Embed(
                title="❌ Error",
                description=f"Error retrieving dataset info: {e}",
                color=EMBED_COLOR
            )
            await ctx.reply(embed=embed, mention_author=False)
            print(f"Info command error: {e}")

    @commands.command(name='search')
    async def search_command(self, ctx, *, search_term: str):
        """Search for datasets by name (case insensitive)"""
        user_id = ctx.author.id
        search_term = search_term.strip().lower()

        if not search_term:
            embed = discord.Embed(
                title="❌ No Search Term",
                description="Please provide a search term.\n**Usage:** `?search <term>`",
                color=EMBED_COLOR
            )
            await ctx.reply(embed=embed, mention_author=False)
            return

        try:
            # Find all datasets for user
            all_datasets = await db.db.datasets.find({"user_id": user_id}).to_list(length=None)

            if not all_datasets:
                embed = discord.Embed(
                    title="📋 Search Results",
                    description="You have no stored datasets. Use `?store <name>` to create one.",
                    color=EMBED_COLOR
                )
                await ctx.reply(embed=embed, mention_author=False)
                return

            # Filter datasets by search term (case insensitive)
            matching_datasets = [d for d in all_datasets if search_term in d["name_lower"]]

            if not matching_datasets:
                embed = discord.Embed(
                    title="🔍 Search Results",
                    description=f"No datasets found containing **'{search_term}'**.",
                    color=EMBED_COLOR
                )
                embed.set_footer(text=f"Searched in {len(all_datasets)} total datasets")
                await ctx.reply(embed=embed, mention_author=False)
                return

            # Get user state for current selection
            user_state = await db.db.user_states.find_one({"user_id": user_id})
            selected_dataset = user_state.get("selected_dataset", "").lower() if user_state else None

            # If results fit in one page, use simple embed
            if len(matching_datasets) <= 24:
                embed = discord.Embed(
                    title=f"🔍 Search Results for '{search_term}'", 
                    color=EMBED_COLOR
                )

                for dataset in matching_datasets:
                    name = dataset["name"]
                    name_lower = dataset["name_lower"]
                    command_count = len(dataset.get("commands", []))
                    last_used = dataset.get("last_used")

                    status = "<:green_dot:1391644125496873010> Selected" if name_lower == selected_dataset else "<:dark:1391644039576682516>"
                    last_used_str = f"<t:{int(last_used.timestamp())}:R>" if last_used else "Never"

                    embed.add_field(
                        name=f"{status} {name}",
                        value=f"Commands: {command_count}\nLast used: {last_used_str}",
                        inline=True
                    )

                embed.set_footer(text=f"Found {len(matching_datasets)} of {len(all_datasets)} datasets")
                await ctx.reply(embed=embed, mention_author=False)
            else:
                # Use pagination for large results
                class SearchPaginationView(discord.ui.View):
                    def __init__(self, datasets, user_id, selected_dataset, search_term, total_datasets, current_page=0):
                        super().__init__(timeout=60)
                        self.datasets = datasets
                        self.user_id = user_id
                        self.selected_dataset = selected_dataset
                        self.search_term = search_term
                        self.total_datasets = total_datasets
                        self.current_page = current_page
                        self.items_per_page = 24
                        self.total_pages = math.ceil(len(datasets) / self.items_per_page)
                        self.add_navigation_buttons()

                    def add_navigation_buttons(self):
                        prev_button = discord.ui.Button(
                            label="◀ Previous", 
                            style=discord.ButtonStyle.secondary,
                            disabled=self.current_page == 0
                        )
                        prev_button.callback = self.previous_page
                        self.add_item(prev_button)

                        page_info = discord.ui.Button(
                            label=f"Page {self.current_page + 1}/{self.total_pages}",
                            style=discord.ButtonStyle.secondary,
                            disabled=True
                        )
                        self.add_item(page_info)

                        next_button = discord.ui.Button(
                            label="Next ▶", 
                            style=discord.ButtonStyle.secondary,
                            disabled=self.current_page >= self.total_pages - 1
                        )
                        next_button.callback = self.next_page
                        self.add_item(next_button)

                    def create_embed(self):
                        start_idx = self.current_page * self.items_per_page
                        end_idx = min(start_idx + self.items_per_page, len(self.datasets))
                        page_datasets = self.datasets[start_idx:end_idx]

                        embed = discord.Embed(
                            title=f"🔍 Search Results for '{self.search_term}' (Page {self.current_page + 1}/{self.total_pages})",
                            color=EMBED_COLOR
                        )

                        for dataset in page_datasets:
                            name = dataset["name"]
                            name_lower = dataset["name_lower"]
                            command_count = len(dataset.get("commands", []))
                            last_used = dataset.get("last_used")

                            status = "<:green_dot:1391644125496873010> Selected" if name_lower == self.selected_dataset else "<:dark:1391644039576682516>"
                            last_used_str = f"<t:{int(last_used.timestamp())}:R>" if last_used else "Never"

                            embed.add_field(
                                name=f"{status} {name}",
                                value=f"Commands: {command_count}\nLast used: {last_used_str}",
                                inline=True
                            )

                        embed.set_footer(text=f"Found {len(self.datasets)} of {self.total_datasets} datasets | Showing {start_idx + 1}-{end_idx}")
                        return embed

                    async def previous_page(self, interaction):
                        if interaction.user.id != self.user_id:
                            await interaction.response.send_message("❌ This is not your search.", ephemeral=True)
                            return
                        self.current_page = max(0, self.current_page - 1)
                        new_view = SearchPaginationView(
                            self.datasets, self.user_id, self.selected_dataset, 
                            self.search_term, self.total_datasets, self.current_page
                        )
                        await interaction.response.edit_message(embed=new_view.create_embed(), view=new_view)

                    async def next_page(self, interaction):
                        if interaction.user.id != self.user_id:
                            await interaction.response.send_message("❌ This is not your search.", ephemeral=True)
                            return
                        self.current_page = min(self.total_pages - 1, self.current_page + 1)
                        new_view = SearchPaginationView(
                            self.datasets, self.user_id, self.selected_dataset, 
                            self.search_term, self.total_datasets, self.current_page
                        )
                        await interaction.response.edit_message(embed=new_view.create_embed(), view=new_view)

                    async def on_timeout(self):
                        for item in self.children:
                            item.disabled = True

                view = SearchPaginationView(
                    matching_datasets, user_id, selected_dataset, 
                    search_term, len(all_datasets)
                )
                embed = view.create_embed()
                await ctx.reply(embed=embed, view=view, mention_author=False)

        except Exception as e:
            embed = discord.Embed(
                title="❌ Error",
                description=f"Error searching datasets: {e}",
                color=EMBED_COLOR
            )
            await ctx.reply(embed=embed, mention_author=False)
            print(f"Search command error: {e}")


async def setup(bot):
    await bot.add_cog(Daycare(bot))
