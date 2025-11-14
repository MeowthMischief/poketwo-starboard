import discord
import re
import json
import os
from datetime import datetime
from discord.ext import commands
from config import EMBED_COLOR

class Unbox(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.pokemon_data = self.load_pokemon_data()

    @property
    def db(self):
        """Get database from main module"""
        import __main__
        return getattr(__main__, 'db', None)

    def load_pokemon_data(self):
        """Load Pokemon data from starboard.txt file"""
        try:
            # Try to load from the same directory as the cog
            starboard_file = os.path.join(os.path.dirname(__file__), '..', 'starboard.txt')
            if not os.path.exists(starboard_file):
                # Fallback to current directory
                starboard_file = 'starboard.txt'

            with open(starboard_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data
        except Exception as e:
            print(f"Error loading Pokemon data: {e}")
            return {}

    def get_gender_emoji(self, gender):
        """Get gender emoji based on gender"""
        if gender == 'male':
            return "<:male:1420708128785170453>"
        elif gender == 'female':
            return "<:female:1420708136943095889>"
        elif gender == 'unknown':
            return "<:unknown:1420708112310210560>"
        else:
            return ""

    def find_pokemon_image_url(self, pokemon_name, is_shiny=False, gender=None, is_gigantamax=False):
        """Find Pokemon image URL from the loaded data with gender and Gigantamax support"""
        # Normalize the pokemon name for matching
        normalized_name = pokemon_name.strip().lower()

        # If it's Gigantamax, search for Gigantamax variant first
        if is_gigantamax:
            # First try to find Gigantamax variant
            gigantamax_name = f"gigantamax {normalized_name}"

            for key, value in self.pokemon_data.items():
                if key.startswith('variant_') and 'gigantamax' in key.lower():
                    pokemon_display_name = value.get('name', '').lower()
                    if gigantamax_name == pokemon_display_name:
                        base_url = value.get('image_url', '')
                        if is_shiny and base_url:
                            # Replace 'images' with 'shiny' for shiny Gigantamax
                            return base_url.replace('/images/', '/shiny/')
                        return base_url

        # Function to search for Pokemon with proper female variant handling
        def search_pokemon(search_name, prefer_female=False):
            # First, try to find exact match
            for key, value in self.pokemon_data.items():
                pokemon_entry_name = value.get('name', '').lower()

                # Handle the case where female variants have "_female" in the name
                if prefer_female and gender == 'female':
                    # First try to find female variant
                    if pokemon_entry_name == f"{search_name}_female":
                        return value.get('image_url', '')

                # Try exact match with the search name
                if pokemon_entry_name == search_name:
                    return value.get('image_url', '')

            # If no exact match, try partial matching
            for key, value in self.pokemon_data.items():
                pokemon_entry_name = value.get('name', '').lower()

                # Handle female variants in partial matching
                if prefer_female and gender == 'female':
                    if f"{search_name}_female" in pokemon_entry_name or pokemon_entry_name in f"{search_name}_female":
                        return value.get('image_url', '')

                # Regular partial matching
                if search_name in pokemon_entry_name or pokemon_entry_name in search_name:
                    return value.get('image_url', '')

            return None

        # Search for Pokemon image URL
        base_url = search_pokemon(normalized_name, prefer_female=True)

        # If female variant not found and we were looking for female, try the base name
        if base_url is None and gender == 'female':
            base_url = search_pokemon(normalized_name, prefer_female=False)

        if base_url and is_shiny:
            # Replace 'images' with 'shiny' for shiny Pokemon
            return base_url.replace('/images/', '/shiny/')

        return base_url

    async def get_starboard_channel(self, guild_id):
        """Get the starboard channel for a guild"""
        if self.db is None:
            return None

        try:
            guild_settings = await self.db.guild_settings.find_one({"guild_id": guild_id})
            if guild_settings:
                return guild_settings.get('starboard_channel_id')
        except Exception as e:
            print(f"Error getting starboard channel: {e}")
        return None

    async def get_global_starboard_channel(self):
        """Get the global starboard channel"""
        if self.db is None:
            return None

        try:
            global_settings = await self.db.global_settings.find_one({"_id": "starboard"})
            if global_settings:
                return global_settings.get('global_starboard_channel_id')
        except Exception as e:
            print(f"Error getting global starboard channel: {e}")
        return None

    async def get_unboxed_by_user(self, message):
        """Get who opened the box from the reply"""
        if not message.reference:
            return None

        try:
            # Try cached first
            if message.reference.resolved:
                return message.reference.resolved.author.id

            # Fetch if not cached
            referenced_message = await message.channel.fetch_message(message.reference.message_id)
            return referenced_message.author.id

        except Exception as e:
            print(f"Error getting unboxed user: {e}")
            return None

    def extract_pokemon_from_text(self, text):
        """Extract Pokemon data from any text using flexible patterns"""
        pokemon_found = []

        # More flexible pattern that handles various formats
        # This pattern looks for: emoji -> Level X -> Pokemon Name -> gender emoji -> (IV%)
        patterns = [
            # Main pattern - handles most cases including Easter Egg format
            r'<:_:\d+>\s*(?:✨\s*)?Level\s+(\d+)\s+(.+?)\s*<:(male|female|unknown):\d+>\s*\((\d+(?:\.\d+)?)%\)',
            # Alternative pattern for cases where spacing might differ
            r'<:_:\d+>\s*(✨\s*)?Level\s+(\d+)\s+(.+?)\s+<:(male|female|unknown):\d+>\s*\((\d+(?:\.\d+)?)%\)',
        ]

        lines = text.split('\n')
        for line in lines:
            line = line.strip()

            # Skip lines that don't contain Pokemon data indicators
            if not ('<:_:' in line and 'Level' in line and '(' in line and '%' in line):
                continue

            # Remove any markdown formatting
            clean_line = line.replace('**', '').replace('- ', '').strip()

            # Check for shiny separately to handle spacing variations
            is_shiny = '✨' in clean_line

            for pattern in patterns:
                match = re.search(pattern, clean_line)
                if match:
                    # Determine which groups correspond to what based on pattern
                    if len(match.groups()) == 4:  # Pattern without shiny group
                        level = match.group(1)
                        pokemon_name_with_gender = match.group(2).strip()
                        gender = match.group(3)
                        iv = float(match.group(4))
                    else:  # Pattern with shiny group
                        if match.group(1):  # Shiny marker found in group
                            is_shiny = True
                        level = match.group(2)
                        pokemon_name_with_gender = match.group(3).strip()
                        gender = match.group(4)
                        iv = float(match.group(5))

                    # Remove gender emoji from pokemon name if it appears there too
                    pokemon_name = re.sub(r'<:(male|female|unknown):\d+>', '', pokemon_name_with_gender).strip()

                    # Debug print to help troubleshoot
                    print(f"DEBUG: Unbox extracted - Pokemon: '{pokemon_name}', Gender: '{gender}', Full captured: '{pokemon_name_with_gender}'")

                    # Check for gigantamax
                    is_gigantamax = pokemon_name.lower().startswith('gigantamax')

                    pokemon_data = {
                        'pokemon_name': pokemon_name,
                        'level': level,
                        'iv': iv,
                        'is_shiny': is_shiny,
                        'is_gigantamax': is_gigantamax,
                        'gender': gender
                    }

                    pokemon_found.append(pokemon_data)
                    break  # Found a match, no need to try other patterns

        return pokemon_found

    def parse_poketwo_unbox_message(self, message, unboxed_by_id=None):
        """Parse Poketwo box opening message to extract Pokemon information"""
        if not message.embeds:
            return []

        embed = message.embeds[0]
        pokemon_found = []

        # Check if this is a box opening message by looking at title keywords
        title = embed.title or ""

        # More flexible title checking - includes all bundle types
        opening_keywords = ['open', 'opening', 'box', 'chest', 'mystery', 'egg', 'eggs', 'bundle', 'puddle', 'rain', 'storm']
        is_opening_message = any(keyword.lower() in title.lower() for keyword in opening_keywords)

        if not is_opening_message:
            return []

        # Try to extract Pokemon from description first
        if embed.description:
            pokemon_from_desc = self.extract_pokemon_from_text(embed.description)
            for pokemon_data in pokemon_from_desc:
                pokemon_data['unboxed_by_id'] = unboxed_by_id
                pokemon_data['message_type'] = 'unbox'
                pokemon_found.append(pokemon_data)

        # Try to extract Pokemon from ALL fields regardless of name
        # This handles any number of bundle fields dynamically
        for field in embed.fields:
            if field.value:  # Check if field has any value
                pokemon_from_field = self.extract_pokemon_from_text(field.value)
                for pokemon_data in pokemon_from_field:
                    pokemon_data['unboxed_by_id'] = unboxed_by_id
                    pokemon_data['message_type'] = 'unbox'
                    pokemon_found.append(pokemon_data)

        return pokemon_found

    def create_unbox_embed(self, pokemon_data, embed_type, message=None):
        """Create embed for unbox"""
        pokemon_name = pokemon_data['pokemon_name']
        level = pokemon_data['level']
        iv = pokemon_data['iv']
        is_shiny = pokemon_data['is_shiny']
        is_gigantamax = pokemon_data['is_gigantamax']
        gender = pokemon_data.get('gender')
        unboxed_by_id = pokemon_data.get('unboxed_by_id')

        # Format IV display
        iv_display = f"{iv}%"

        # Get gender emoji
        gender_emoji = self.get_gender_emoji(gender)

        # Format Pokemon name with gender emoji - always include if we have gender info
        if gender_emoji:
            pokemon_display = f"{pokemon_name} {gender_emoji}"
        else:
            pokemon_display = pokemon_name

        # Debug print to help troubleshoot
        print(f"DEBUG: Creating unbox embed - Pokemon: '{pokemon_name}', Gender: '{gender}', Gender Emoji: '{gender_emoji}', Display: '{pokemon_display}'")

        # Get Pokemon image URL with gender and Gigantamax support
        image_url = self.find_pokemon_image_url(pokemon_name, is_shiny, gender, is_gigantamax)

        embed = discord.Embed(color=EMBED_COLOR, timestamp=datetime.utcnow())

        if embed_type == 'gigantamax_shiny':
            embed.title = "<:gigantamax:1420708122267226202> ✨ Gigantamax Shiny Unbox Detected ✨ <:gigantamax:1420708122267226202>"
        elif embed_type == 'gigantamax':
            embed.title = "<:gigantamax:1420708122267226202> Gigantamax Unbox Detected <:gigantamax:1420708122267226202>"
        elif embed_type == 'shiny':
            embed.title = "<a:animatedgiftbox:1421047436625055754>  ✨ Shiny Unbox Detected ✨ <a:animatedgiftbox:1421047436625055754> "
        elif embed_type == 'iv_high':
            embed.title = "<:giftbox:1421047453511323658> 📈 High IV Unboxed 📈 <:giftbox:1421047453511323658>"
        elif embed_type == 'iv_low':
            embed.title = "<:giftbox:1421047453511323658> 📉 Low IV Unboxed 📉 <:giftbox:1421047453511323658>"

        # Build description
        base_description = f"**Pokémon:** {pokemon_display}\n**Level:** {level}\n**IV:** {iv_display}"
        if unboxed_by_id:
            embed.description = f"**Unboxed By:** <@{unboxed_by_id}>\n{base_description}"
        else:
            embed.description = base_description

        if image_url:
            embed.set_thumbnail(url=image_url)

        # Create view with jump to message button
        view = discord.ui.View()
        if message:
            jump_button = discord.ui.Button(
                label="Jump to Message",
                url=message.jump_url,
                emoji="🔗",
                style=discord.ButtonStyle.link
            )
            view.add_item(jump_button)

        return embed, view

    async def send_to_starboard_channels(self, guild, pokemon_list, original_message=None):
        """Send unbox data to appropriate starboard channels"""
        # Get server starboard channel
        server_starboard_id = await self.get_starboard_channel(guild.id)
        server_starboard_channel = None
        if server_starboard_id:
            server_starboard_channel = guild.get_channel(server_starboard_id)

        # Get global starboard channel
        global_starboard_id = await self.get_global_starboard_channel()
        global_starboard_channel = None
        if global_starboard_id:
            global_starboard_channel = self.bot.get_channel(global_starboard_id)

        # Process each Pokemon that meets criteria
        for pokemon_data in pokemon_list:
            is_shiny = pokemon_data['is_shiny']
            is_gigantamax = pokemon_data['is_gigantamax']
            iv = pokemon_data['iv']

            # Check if this Pokemon meets starboard criteria
            if not (is_shiny or is_gigantamax or iv >= 90 or iv <= 10):
                continue

            embeds_to_send = []

            # Determine what type of unbox this is and create separate embeds for each criteria met
            if is_gigantamax and is_shiny:
                # Gigantamax Shiny (very rare) - send one combined embed
                embed, view = self.create_unbox_embed(pokemon_data, 'gigantamax_shiny', original_message)
                embeds_to_send.append((embed, view))
            elif is_gigantamax:
                # Gigantamax only
                embed, view = self.create_unbox_embed(pokemon_data, 'gigantamax', original_message)
                embeds_to_send.append((embed, view))
            elif is_shiny:
                # Shiny only
                embed, view = self.create_unbox_embed(pokemon_data, 'shiny', original_message)
                embeds_to_send.append((embed, view))

            # Check for rare IV - send separate embed even if Pokemon is already shiny/gigantamax
            # (unless it's gigantamax + shiny combo which gets special treatment above)
            if not (is_gigantamax and is_shiny):
                if iv >= 90:
                    embed, view = self.create_unbox_embed(pokemon_data, 'iv_high', original_message)
                    embeds_to_send.append((embed, view))
                elif iv <= 10:
                    embed, view = self.create_unbox_embed(pokemon_data, 'iv_low', original_message)
                    embeds_to_send.append((embed, view))

            # Send each embed separately to server starboard
            if server_starboard_channel and embeds_to_send:
                for embed, view in embeds_to_send:
                    try:
                        await server_starboard_channel.send(embed=embed, view=view)
                    except Exception as e:
                        print(f"Error sending to server starboard: {e}")

            # Send each embed separately to global starboard
            if global_starboard_channel and embeds_to_send:
                for embed, view in embeds_to_send:
                    try:
                        await global_starboard_channel.send(embed=embed, view=view)
                    except Exception as e:
                        print(f"Error sending to global starboard: {e}")

    @commands.command(name="bcheck")
    @commands.has_permissions(administrator=True)
    async def box_check_command(self, ctx, *, input_data=None):
        """Manually check a Poketwo box opening message and send to starboard if it meets criteria

        Usage:
        - Reply to a message: m!bcheck
        - Provide message ID: m!bcheck 123456789012345678
        """

        original_message = None
        unboxed_by_id = None

        if input_data is None:
            # User must be replying to a message
            if ctx.message.reference and ctx.message.reference.resolved:
                original_message = ctx.message.reference.resolved

                # Get the unboxed user from the reply
                unboxed_by_id = await self.get_unboxed_by_user(original_message)
            else:
                await ctx.reply("Please provide a message ID or reply to a Poketwo box opening message.\n"
                               "Examples:\n"
                               "`m!bcheck 123456789012345678` (message ID)\n"
                               "Or reply to a message with just `m!boxcheck`")
                return
        else:
            # Check if input_data is a message ID (numeric)
            if input_data.strip().isdigit():
                message_id = int(input_data.strip())
                try:
                    # Try to fetch the message from the current channel first
                    try:
                        original_message = await ctx.channel.fetch_message(message_id)
                    except discord.NotFound:
                        # If not found in current channel, search in all channels in the guild
                        found_message = None
                        for channel in ctx.guild.text_channels:
                            if channel.permissions_for(ctx.guild.me).read_message_history:
                                try:
                                    found_message = await channel.fetch_message(message_id)
                                    original_message = found_message
                                    break
                                except (discord.NotFound, discord.Forbidden):
                                    continue

                        if not found_message:
                            await ctx.reply(f"❌ Could not find message with ID `{message_id}` in this server.")
                            return

                    # Check if the message is from Poketwo
                    if original_message.author.id != 716390085896962058:
                        await ctx.reply(f"❌ The message with ID `{message_id}` is not from Poketwo.")
                        return

                    # Get the unboxed user from the reply
                    unboxed_by_id = await self.get_unboxed_by_user(original_message)

                except ValueError:
                    await ctx.reply(f"❌ Invalid message ID: `{input_data.strip()}`")
                    return
                except discord.Forbidden:
                    await ctx.reply(f"❌ I don't have permission to access the message with ID `{message_id}`.")
                    return
                except Exception as e:
                    await ctx.reply(f"❌ Error fetching message: {str(e)}")
                    return
            else:
                await ctx.reply("❌ Please provide a valid message ID or reply to a message.")
                return

        # Try to parse as box opening message
        pokemon_list = self.parse_poketwo_unbox_message(original_message, unboxed_by_id)

        if not pokemon_list:
            await ctx.reply("❌ Invalid message format. Please make sure it's a proper Poketwo box opening message.")
            return

        # Check which Pokemon meet starboard criteria
        qualifying_pokemon = []
        for pokemon_data in pokemon_list:
            is_shiny = pokemon_data['is_shiny']
            is_gigantamax = pokemon_data['is_gigantamax']
            iv = pokemon_data['iv']

            if is_shiny or is_gigantamax or iv >= 90 or iv <= 10:
                qualifying_pokemon.append(pokemon_data)

        if not qualifying_pokemon:
            pokemon_summary = []
            for pokemon_data in pokemon_list:
                # Format pokemon name with gender for error message
                gender_emoji = self.get_gender_emoji(pokemon_data.get('gender'))
                pokemon_display = f"{pokemon_data['pokemon_name']} {gender_emoji}" if gender_emoji else pokemon_data['pokemon_name']
                pokemon_summary.append(f"**{pokemon_display}** (Level {pokemon_data['level']}, {pokemon_data['iv']}%)")

            summary_text = "\n".join(pokemon_summary) if pokemon_summary else "No Pokemon found"
            await ctx.reply(f"❌ No Pokemon in this unbox meet starboard criteria.\n"
                           f"**Found Pokemon:**\n{summary_text}\n"
                           f"**Criteria:** Shiny, Gigantamax, or IV ≥90% or ≤10%")
            return

        # Send to starboard
        await self.send_to_starboard_channels(ctx.guild, qualifying_pokemon, original_message)

        # Create summary of what was sent
        summary_lines = []
        for pokemon_data in qualifying_pokemon:
            criteria_met = []
            if pokemon_data['is_shiny']:
                criteria_met.append("✨ Shiny")
            if pokemon_data['is_gigantamax']:
                criteria_met.append("<:gigantamax:1420708122267226202> Gigantamax")
            if pokemon_data['iv'] >= 90:
                criteria_met.append(f"📈 High IV ({pokemon_data['iv']}%)")
            elif pokemon_data['iv'] <= 10:
                criteria_met.append(f"📉 Low IV ({pokemon_data['iv']}%)")

            criteria_text = ", ".join(criteria_met)
            # Format pokemon name with gender for success message
            gender_emoji = self.get_gender_emoji(pokemon_data.get('gender'))
            pokemon_display = f"{pokemon_data['pokemon_name']} {gender_emoji}" if gender_emoji else pokemon_data['pokemon_name']
            summary_lines.append(f"**{pokemon_display}** - {criteria_text}")

        # Add debug info about unboxed_by_id
        debug_info = ""
        if unboxed_by_id:
            debug_info = f"\n**Unboxed By:** <@{unboxed_by_id}>"
        else:
            debug_info = f"\n**Unboxed By:** Could not determine"

        # Add message source info
        if original_message:
            debug_info += f"\n**Message:** [Jump to original]({original_message.jump_url})"

        summary_text = "\n".join(summary_lines)
        await ctx.reply(f"✅ {len(qualifying_pokemon)} Pokemon sent to starboard!\n"
                       f"{summary_text}{debug_info}")

    @box_check_command.error
    async def box_check_error(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.reply("You need administrator permissions to use this command.")
        else:
            # Log unexpected errors
            print(f"Unexpected error in boxcheck: {error}")
            await ctx.reply("❌ An unexpected error occurred. Please try again.")

    @commands.Cog.listener()
    async def on_message(self, message):
        """Listen for Poketwo box opening messages"""
        # Only process messages from Poketwo
        if message.author.id != 716390085896962058:
            return

        # Check if it's a box opening message (must have embeds)
        if not message.embeds:
            return

        embed = message.embeds[0]
        title = embed.title or ""

        # More flexible title checking for all bundle types and opening formats
        opening_keywords = ['open', 'opening', 'box', 'chest', 'mystery', 'egg', 'eggs', 'bundle', 'puddle', 'rain', 'storm']
        is_opening_message = any(keyword.lower() in title.lower() for keyword in opening_keywords)

        if not is_opening_message:
            return

        # Get the user who opened the box from the reply
        unboxed_by_id = await self.get_unboxed_by_user(message)
        pokemon_list = self.parse_poketwo_unbox_message(message, unboxed_by_id)

        if not pokemon_list:
            return

        # Filter Pokemon that meet starboard criteria
        qualifying_pokemon = []
        for pokemon_data in pokemon_list:
            is_shiny = pokemon_data['is_shiny']
            is_gigantamax = pokemon_data['is_gigantamax']
            iv = pokemon_data['iv']

            # Check criteria: shiny, gigantamax, or rare IV
            if is_shiny or is_gigantamax or iv >= 90 or iv <= 10:
                qualifying_pokemon.append(pokemon_data)

        if qualifying_pokemon:
            await self.send_to_starboard_channels(message.guild, qualifying_pokemon, message)

async def setup(bot):
    await bot.add_cog(Unbox(bot))
