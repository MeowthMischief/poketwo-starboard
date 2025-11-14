import discord
import re
import json
import os
from datetime import datetime
from discord.ext import commands
from config import EMBED_COLOR

class Starboard(commands.Cog):
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

        # Special case for Eternatus - use "eternamax" instead of "gigantamax" when it has gigantamax factor
        if is_gigantamax and normalized_name == "eternatus":
            # Search for Eternamax variant
            eternamax_name = "eternamax eternatus"

            for key, value in self.pokemon_data.items():
                if key.startswith('variant_') and 'eternamax' in key.lower():
                    pokemon_display_name = value.get('name', '').lower()
                    if eternamax_name == pokemon_display_name:
                        base_url = value.get('image_url', '')
                        if is_shiny and base_url:
                            # Replace 'images' with 'shiny' for shiny Eternamax
                            return base_url.replace('/images/', '/shiny/')
                        return base_url

        # If it's Gigantamax (but not Eternatus), search for Gigantamax variant first
        elif is_gigantamax:
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

    async def set_starboard_channel(self, guild_id, channel_id):
        """Set the starboard channel for a guild"""
        if self.db is None:
            return "Database not available"

        try:
            await self.db.guild_settings.update_one(
                {"guild_id": guild_id},
                {"$set": {"starboard_channel_id": channel_id}},
                upsert=True
            )
            return "Starboard channel set successfully!"
        except Exception as e:
            print(f"Error setting starboard channel: {e}")
            return f"Database error: {str(e)[:100]}"

    async def set_global_starboard_channel(self, channel_id):
        """Set the global starboard channel"""
        if self.db is None:
            return "Database not available"

        try:
            await self.db.global_settings.update_one(
                {"_id": "starboard"},
                {"$set": {"global_starboard_channel_id": channel_id}},
                upsert=True
            )
            return "Global starboard channel set successfully!"
        except Exception as e:
            print(f"Error setting global starboard channel: {e}")
            return f"Database error: {str(e)[:100]}"

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

    async def get_server_settings(self, guild_id):
        """Get server settings including rare role, regional role, and starboard channel"""
        if self.db is None:
            return None, None, None

        try:
            guild_settings = await self.db.guild_settings.find_one({"guild_id": guild_id})
            if guild_settings:
                return (
                    guild_settings.get('rare_role_id'),
                    guild_settings.get('regional_role_id'),
                    guild_settings.get('starboard_channel_id')
                )
        except Exception as e:
            print(f"Error getting server settings: {e}")
        return None, None, None

    def parse_poketwo_catch_message(self, message_content):
        """Parse Poketwo catch message to extract relevant information"""
        # Updated pattern to properly capture everything including gender emoji
        catch_pattern = r"Congratulations <@!?(\d+)>! You caught a Level (\d+) (.+?)(?:\s+\((\d+\.?\d*)%\))?!"

        match = re.search(catch_pattern, message_content)
        if not match:
            return None

        user_id = match.group(1)
        level = match.group(2)
        pokemon_name_with_gender = match.group(3).strip()
        iv_str = match.group(4)  # This could be None if IV is hidden

        # Handle IV - if not present, it's hidden
        if iv_str:
            # Keep the original string format to preserve trailing zeros
            iv = iv_str
        else:
            iv = "Hidden"

        # Extract gender from emoji - check the entire message content for gender emojis
        gender = None
        pokemon_name = pokemon_name_with_gender

        # First, let's check the full message content for gender emojis
        if re.search(r'<:male:\d+>', message_content):
            gender = 'male'
            # Remove gender emoji from pokemon name if it's there
            pokemon_name = re.sub(r'<:male:\d+>', '', pokemon_name_with_gender).strip()
        elif re.search(r'<:female:\d+>', message_content):
            gender = 'female'
            # Remove gender emoji from pokemon name if it's there
            pokemon_name = re.sub(r'<:female:\d+>', '', pokemon_name_with_gender).strip()
        elif re.search(r'<:unknown:\d+>', message_content):
            gender = 'unknown'
            # Remove gender emoji from pokemon name if it's there
            pokemon_name = re.sub(r'<:unknown:\d+>', '', pokemon_name_with_gender).strip()


        # Check for shiny
        is_shiny = "These colors seem unusual... ✨" in message_content

        # Check for gigantamax
        is_gigantamax = "Woah! It seems that this pokémon has the Gigantamax Factor..." in message_content

        # Check for shiny streak reset
        shiny_chain = None
        chain_pattern = r"Shiny streak reset\. \(\*\*(\d+)\*\*\)"
        chain_match = re.search(chain_pattern, message_content)
        if chain_match:
            shiny_chain = chain_match.group(1)

        return {
            'user_id': user_id,
            'level': level,
            'pokemon_name': pokemon_name,
            'iv': iv,
            'is_shiny': is_shiny,
            'is_gigantamax': is_gigantamax,
            'shiny_chain': shiny_chain,
            'gender': gender,
            'message_type': 'catch'
        }

    def parse_poketwo_missingno_message(self, message_content):
        """Parse Poketwo MissingNo. catch message"""
        # Pattern for MissingNo. with IV
        missingno_pattern1 = r"Congratulations <@!?(\d+)>! You caught a Level \?\?\? MissingNo\.(?:<:[^:]+:\d+>)? \(\?\?\?%\)!"
        # Pattern for MissingNo. without IV
        missingno_pattern2 = r"Congratulations <@!?(\d+)>! You caught a Level \?\?\? MissingNo\.(?:<:[^:]+:\d+>)!"

        match = re.search(missingno_pattern1, message_content) or re.search(missingno_pattern2, message_content)
        if not match:
            return None

        user_id = match.group(1)

        # Extract gender from MissingNo message if present - check the full message content
        gender = None
        if re.search(r'<:male:\d+>', message_content):
            gender = 'male'
        elif re.search(r'<:female:\d+>', message_content):
            gender = 'female'
        elif re.search(r'<:unknown:\d+>', message_content):
            gender = 'unknown'

        # Check for shiny MissingNo. - THIS WAS THE MISSING PART!
        is_shiny = "These colors seem unusual... ✨" in message_content

        # Debug print
        print(f"DEBUG: MissingNo parsed - Gender: '{gender}', Shiny: {is_shiny}")

        return {
            'user_id': user_id,
            'level': '???',
            'pokemon_name': 'MissingNo.',
            'iv': '???',
            'is_shiny': is_shiny,  # Now properly detects shiny
            'is_gigantamax': False,
            'gender': gender,
            'message_type': 'missingno'
        }

    def create_catch_embed(self, catch_data, embed_type, message=None):
        """Create embed for catch messages with combined criteria"""
        message_type = catch_data.get('message_type', 'catch')
        pokemon_name = catch_data['pokemon_name']
        level = catch_data['level']
        iv = catch_data['iv']
        is_shiny = catch_data['is_shiny']
        is_gigantamax = catch_data['is_gigantamax']
        gender = catch_data.get('gender')

        # Format IV display
        if iv == "Hidden":
            iv_display = "Hidden"
        elif iv == "???":
            iv_display = "???"
        else:
            iv_display = f"{iv}%"

        # Get gender emoji
        gender_emoji = self.get_gender_emoji(gender)

        # Special handling for Eternatus with Gigantamax factor
        display_pokemon_name = pokemon_name
        if is_gigantamax and pokemon_name.lower() == "eternatus":
            display_pokemon_name = "Eternamax Eternatus"
        elif is_gigantamax:
            display_pokemon_name = f"Gigantamax {pokemon_name}"

        # Format Pokemon name with gender emoji - always include if we have gender info
        if gender_emoji:
            pokemon_display = f"{display_pokemon_name} {gender_emoji}"
        else:
            pokemon_display = display_pokemon_name

        # Get Pokemon image URL with gender and Gigantamax support
        image_url = self.find_pokemon_image_url(pokemon_name, is_shiny, gender, is_gigantamax)

        embed = discord.Embed(color=EMBED_COLOR, timestamp=datetime.utcnow())

        if message_type == 'catch':
            user_id = catch_data['user_id']
            shiny_chain = catch_data.get('shiny_chain')

            # Determine embed type and title based on all combinations
            if embed_type == 'shiny_gigantamax_rare_iv_high':
                # Triple combo - Shiny + Gigantamax + High IV
                if pokemon_name.lower() == "eternatus":
                    embed.title = "✨ <:gigantamax:1420708122267226202> 📈 Shiny Eternamax High IV Catch Detected 📈 <:gigantamax:1420708122267226202> ✨"
                else:
                    embed.title = "✨ <:gigantamax:1420708122267226202> 📈 Shiny Gmax High IV Catch Detected 📈 <:gigantamax:1420708122267226202> ✨"

            elif embed_type == 'shiny_gigantamax_rare_iv_low':
                # Triple combo - Shiny + Gigantamax + Low IV
                if pokemon_name.lower() == "eternatus":
                    embed.title = "✨ <:gigantamax:1420708122267226202> 📉 Shiny Eternamax Low IV Catch Detected 📉 <:gigantamax:1420708122267226202> ✨"
                else:
                    embed.title = "✨ <:gigantamax:1420708122267226202> 📉 Shiny Gmax Low IV Catch Detected 📉 <:gigantamax:1420708122267226202> ✨"

            elif embed_type == 'shiny_gigantamax':
                # Shiny + Gigantamax
                if pokemon_name.lower() == "eternatus":
                    embed.title = "✨ <:gigantamax:1420708122267226202> Shiny Eternamax Catch Detected <:gigantamax:1420708122267226202> ✨"
                else:
                    embed.title = "✨ <:gigantamax:1420708122267226202> Shiny Gigantamax Catch Detected <:gigantamax:1420708122267226202> ✨"

            elif embed_type == 'shiny_rare_iv_high':
                # Shiny + High IV
                embed.title = "✨ 📈 Shiny High IV Catch Detected 📈 ✨"

            elif embed_type == 'shiny_rare_iv_low':
                # Shiny + Low IV
                embed.title = "✨ 📉 Shiny Low IV Catch Detected 📉 ✨"

            elif embed_type == 'gigantamax_rare_iv_high':
                # Gigantamax + High IV
                if pokemon_name.lower() == "eternatus":
                    embed.title = "<:gigantamax:1420708122267226202> 📈 Eternamax High IV Catch Detected 📈 <:gigantamax:1420708122267226202>"
                else:
                    embed.title = "<:gigantamax:1420708122267226202> 📈 Gigantamax High IV Catch Detected 📈 <:gigantamax:1420708122267226202>"

            elif embed_type == 'gigantamax_rare_iv_low':
                # Gigantamax + Low IV
                if pokemon_name.lower() == "eternatus":
                    embed.title = "<:gigantamax:1420708122267226202> 📉 Eternamax Low IV Catch Detected 📉 <:gigantamax:1420708122267226202>"
                else:
                    embed.title = "<:gigantamax:1420708122267226202> 📉 Gigantamax Low IV Catch Detected 📉 <:gigantamax:1420708122267226202>"

            elif embed_type == 'gigantamax':
                # Gigantamax only
                if pokemon_name.lower() == "eternatus":
                    embed.title = "<:gigantamax:1420708122267226202> Eternamax Catch Detected <:gigantamax:1420708122267226202>"
                else:
                    embed.title = "<:gigantamax:1420708122267226202> Gigantamax Catch Detected <:gigantamax:1420708122267226202>"

            elif embed_type == 'shiny':
                # Shiny only
                embed.title = "✨ Shiny Catch Detected ✨"

            elif embed_type == 'iv_high':
                # High IV only
                embed.title = "📈 High IV Catch Detected 📈"

            elif embed_type == 'iv_low':
                # Low IV only
                embed.title = "📉 Low IV Catch Detected 📉"

            # Standard description for all catch types
            embed.description = f"**Caught By:** <@{user_id}>\n**Pokémon:** {pokemon_display}\n**Level:** {level}\n**IV:** {iv_display}"
            if shiny_chain:
                embed.description += f"\n**Chain:** {shiny_chain}"

        elif message_type == 'missingno':
            user_id = catch_data['user_id']

            # Handle shiny MissingNo.
            if is_shiny:
                embed.title = "✨ Shiny MissingNo. Detected ✨"
            else:
                embed.title = "<:missingno:1420713960465760357> MissingNo. Detected <:missingno:1420713960465760357>"

            embed.description = f"**Caught By:** <@{user_id}>\n**Pokémon:** {pokemon_display}\n**Level:** ???\n**IV:** {iv_display}"

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

    async def send_to_starboard_channels(self, guild, catch_data, original_message=None):
        """Send catch data to appropriate starboard channels with combined criteria"""
        is_shiny = catch_data['is_shiny']
        is_gigantamax = catch_data['is_gigantamax']
        iv = catch_data['iv']
        message_type = catch_data.get('message_type', 'catch')
        pokemon_name = catch_data['pokemon_name']

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

        # Handle MissingNo. - always send regardless of other criteria
        if message_type == 'missingno':
            embed, view = self.create_catch_embed(catch_data, 'missingno', original_message)

            # Send to server starboard
            if server_starboard_channel:
                try:
                    await server_starboard_channel.send(embed=embed, view=view)
                except Exception as e:
                    print(f"Error sending to server starboard: {e}")

            # Send to global starboard
            if global_starboard_channel:
                try:
                    await global_starboard_channel.send(embed=embed, view=view)
                except Exception as e:
                    print(f"Error sending to global starboard: {e}")
            return

        # Handle Eternatus - only shiny and gigantamax criteria, no IV
        if pokemon_name.lower() == "eternatus":
            embed_type = None

            if is_shiny and is_gigantamax:
                embed_type = 'shiny_gigantamax'
            elif is_gigantamax:
                embed_type = 'gigantamax'
            elif is_shiny:
                embed_type = 'shiny'

            if embed_type:
                embed, view = self.create_catch_embed(catch_data, embed_type, original_message)

                # Send to server starboard
                if server_starboard_channel:
                    try:
                        await server_starboard_channel.send(embed=embed, view=view)
                    except Exception as e:
                        print(f"Error sending to server starboard: {e}")

                # Send to global starboard
                if global_starboard_channel:
                    try:
                        await global_starboard_channel.send(embed=embed, view=view)
                    except Exception as e:
                        print(f"Error sending to global starboard: {e}")
            return

        # Handle regular Pokemon with all combinations
        # Check IV criteria first
        iv_value = None
        iv_type = None
        if iv != "Hidden" and iv != "???":
            try:
                iv_value = float(iv)
                if iv_value >= 90:
                    iv_type = 'high'
                elif iv_value <= 10:
                    iv_type = 'low'
            except ValueError:
                iv_value = None

        # Determine the single embed type based on all combinations
        embed_type = None

        if is_shiny and is_gigantamax and iv_type:
            # Triple combination
            if iv_type == 'high':
                embed_type = 'shiny_gigantamax_rare_iv_high'
            else:  # low
                embed_type = 'shiny_gigantamax_rare_iv_low'

        elif is_shiny and is_gigantamax:
            # Shiny + Gigantamax
            embed_type = 'shiny_gigantamax'

        elif is_shiny and iv_type:
            # Shiny + Rare IV
            if iv_type == 'high':
                embed_type = 'shiny_rare_iv_high'
            else:  # low
                embed_type = 'shiny_rare_iv_low'

        elif is_gigantamax and iv_type:
            # Gigantamax + Rare IV
            if iv_type == 'high':
                embed_type = 'gigantamax_rare_iv_high'
            else:  # low
                embed_type = 'gigantamax_rare_iv_low'

        elif is_shiny:
            # Shiny only
            embed_type = 'shiny'

        elif is_gigantamax:
            # Gigantamax only
            embed_type = 'gigantamax'

        elif iv_type:
            # Rare IV only
            if iv_type == 'high':
                embed_type = 'iv_high'
            else:  # low
                embed_type = 'iv_low'

        # Send the single combined embed if any criteria met
        if embed_type:
            embed, view = self.create_catch_embed(catch_data, embed_type, original_message)

            # Send to server starboard
            if server_starboard_channel:
                try:
                    await server_starboard_channel.send(embed=embed, view=view)
                except Exception as e:
                    print(f"Error sending to server starboard: {e}")

            # Send to global starboard
            if global_starboard_channel:
                try:
                    await global_starboard_channel.send(embed=embed, view=view)
                except Exception as e:
                    print(f"Error sending to global starboard: {e}")

    # Update the manualcheck command to work with new system
    @commands.command(name="manualcheck")
    @commands.has_permissions(administrator=True)
    async def manual_check_command(self, ctx, *, input_data=None):
        """Manually check a Poketwo catch message and send to starboard if it meets criteria"""

        original_message = None
        catch_message = None

        if input_data is None:
            # User must be replying to a message
            if ctx.message.reference and ctx.message.reference.resolved:
                catch_message = ctx.message.reference.resolved.content
                original_message = ctx.message.reference.resolved
            else:
                await ctx.reply("Please provide a Poketwo catch message, message ID, or reply to one.\n"
                               "Examples:\n"
                               "`m!manualcheck 123456789012345678` (message ID)\n"
                               "`m!manualcheck Congratulations <@123456789>! You caught a Level 50 Pikachu (95.5%)!`\n"
                               "Or reply to a message with just `m!manualcheck`")
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

                    catch_message = original_message.content

                    # Check if the message is from Poketwo
                    if original_message.author.id != 716390085896962058:
                        await ctx.reply(f"❌ The message with ID `{message_id}` is not from Poketwo.")
                        return

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
                # Treat as message content
                catch_message = input_data

        # Try to parse as different message types
        catch_data = None
        message_type = None

        # Try MissingNo. first (most specific)
        catch_data = self.parse_poketwo_missingno_message(catch_message)
        if catch_data:
            message_type = "MissingNo. catch"
        else:
            # Try catch message
            catch_data = self.parse_poketwo_catch_message(catch_message)
            if catch_data:
                message_type = "catch"

        if not catch_data:
            await ctx.reply("❌ Invalid message format. Please make sure it's a proper Poketwo catch or MissingNo. message.")
            return

        # Check if this meets starboard criteria using the new system
        is_shiny = catch_data['is_shiny']
        is_gigantamax = catch_data['is_gigantamax']
        iv = catch_data['iv']
        pokemon_name = catch_data['pokemon_name']
        level = catch_data['level']
        gender = catch_data.get('gender')

        criteria_met = []

        # MissingNo. always meets criteria
        if catch_data.get('message_type') == 'missingno':
            criteria_met.append("❓ MissingNo.")
            if is_shiny:
                criteria_met.append("✨ Shiny")
        elif pokemon_name.lower() == "eternatus":
            # Eternatus - only shiny and gigantamax criteria
            if is_shiny:
                criteria_met.append("✨ Shiny")
            if is_gigantamax:
                criteria_met.append("<:gigantamax:1420708122267226202> Eternamax")
        else:
            # Regular Pokemon - all criteria
            if is_shiny:
                criteria_met.append("✨ Shiny")
            if is_gigantamax:
                criteria_met.append("<:gigantamax:1420708122267226202> Gigantamax")

            # Check IV criteria
            iv_value = None
            if iv != "Hidden" and iv != "???":
                try:
                    iv_value = float(iv)
                except ValueError:
                    iv_value = None

            if iv_value is not None:
                if iv_value >= 90:
                    criteria_met.append(f"📈 High IV ({iv}%)")
                elif iv_value <= 10:
                    criteria_met.append(f"📉 Low IV ({iv}%)")

        if not criteria_met:
            # Format IV display for error message
            if iv == "Hidden":
                iv_display = "Hidden"
            elif iv == "???":
                iv_display = "???"
            else:
                iv_display = f"{iv}%"

            # Format pokemon name with gender for error message
            gender_emoji = self.get_gender_emoji(gender)
            pokemon_display = f"{pokemon_name}{gender_emoji}" if gender_emoji else pokemon_name

            await ctx.reply(f"❌ This {message_type} doesn't meet starboard criteria.\n"
                           f"**Pokémon:** {pokemon_display}\n"
                           f"**Level:** {level}\n"
                           f"**IV:** {iv_display} (need ≥90% or ≤10% for IV criteria)\n"
                           f"**Shiny:** {'Yes' if is_shiny else 'No'}\n"
                           f"**Gigantamax:** {'Yes' if is_gigantamax else 'No'}")
            return

        # Send to starboard using the new combined system
        await self.send_to_starboard_channels(ctx.guild, catch_data, original_message)

        criteria_text = ", ".join(criteria_met)
        # Format IV for success message
        if iv == "Hidden":
            iv_display = "Hidden"
        elif iv == "???":
            iv_display = "???"
        else:
            iv_display = f"{iv}%"

        # Format pokemon name with gender for success message
        gender_emoji = self.get_gender_emoji(gender)
        pokemon_display = f"{pokemon_name}{gender_emoji}" if gender_emoji else pokemon_name

        # Add message source info
        debug_info = ""
        if original_message:
            debug_info = f"\n**Message:** [Jump to original]({original_message.jump_url})"

        await ctx.reply(f"✅ {message_type.capitalize()} sent to starboard!\n"
                       f"**Criteria met:** {criteria_text}\n"
                       f"**Pokémon:** {pokemon_display} (Level {level}, {iv_display}){debug_info}")

    @manual_check_command.error
    async def manual_check_error(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.reply("You need administrator permissions to use this command.")
        else:
            # Log unexpected errors
            print(f"Unexpected error in manualcheck: {error}")
            await ctx.reply("❌ An unexpected error occurred. Please try again.")

    @commands.command(name="starboard-channel")
    @commands.has_permissions(administrator=True)
    async def starboard_channel_command(self, ctx, channel: discord.TextChannel = None):
        """Set the starboard channel for this server"""
        if channel is None:
            # Try to parse channel from mention or ID
            if ctx.message.content.count(' ') > 0:
                channel_mention = ctx.message.content.split(' ', 1)[1].strip()

                # Try to get channel by ID if it's a number
                if channel_mention.isdigit():
                    channel = ctx.guild.get_channel(int(channel_mention))
                # Try to parse mention
                elif channel_mention.startswith('<#') and channel_mention.endswith('>'):
                    channel_id = channel_mention[2:-1]
                    if channel_id.isdigit():
                        channel = ctx.guild.get_channel(int(channel_id))

        if channel is None:
            await ctx.reply("Please provide a valid channel mention or ID.")
            return

        if channel.guild != ctx.guild:
            await ctx.reply("The channel must be in this server.")
            return

        result = await self.set_starboard_channel(ctx.guild.id, channel.id)
        await ctx.reply(f"{result} Starboard channel set to {channel.mention}")

    @starboard_channel_command.error
    async def starboard_channel_error(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.reply("You need administrator permissions to use this command.")
        elif isinstance(error, commands.BadArgument):
            await ctx.reply("Invalid channel mention or ID.")

    @commands.command(name="globalstarboard-channel")
    @commands.is_owner()
    async def global_starboard_channel_command(self, ctx, channel: discord.TextChannel = None):
        """Set the global starboard channel (bot owner only)"""
        if channel is None:
            # Try to parse channel from mention or ID
            if ctx.message.content.count(' ') > 0:
                channel_mention = ctx.message.content.split(' ', 1)[1].strip()

                # Try to get channel by ID if it's a number
                if channel_mention.isdigit():
                    channel = self.bot.get_channel(int(channel_mention))
                # Try to parse mention
                elif channel_mention.startswith('<#') and channel_mention.endswith('>'):
                    channel_id = channel_mention[2:-1]
                    if channel_id.isdigit():
                        channel = self.bot.get_channel(int(channel_id))

        if channel is None:
            await ctx.reply("Please provide a valid channel mention or ID.")
            return

        result = await self.set_global_starboard_channel(channel.id)
        await ctx.reply(f"{result} Global starboard channel set to {channel.mention}")

    @global_starboard_channel_command.error
    async def global_starboard_channel_error(self, ctx, error):
        if isinstance(error, commands.NotOwner):
            await ctx.reply("Only the bot owner can use this command.")
        elif isinstance(error, commands.BadArgument):
            await ctx.reply("Invalid channel mention or ID.")

    @commands.command(name="serverpage")
    async def serverpage_command(self, ctx):
        """Show server settings including rare role, regional role, and starboard channel"""
        rare_role_id, regional_role_id, starboard_channel_id = await self.get_server_settings(ctx.guild.id)

        embed = discord.Embed(
            title=f"Server Settings for {ctx.guild.name}",
            color=EMBED_COLOR,
            timestamp=datetime.utcnow()
        )

        # Rare role
        if rare_role_id:
            embed.add_field(name="Rare Role", value=f"<@&{rare_role_id}>", inline=True)
        else:
            embed.add_field(name="Rare Role", value="Not set", inline=True)

        # Regional role
        if regional_role_id:
            embed.add_field(name="Regional Role", value=f"<@&{regional_role_id}>", inline=True)
        else:
            embed.add_field(name="Regional Role", value="Not set", inline=True)

        # Starboard channel
        if starboard_channel_id:
            embed.add_field(name="Starboard Channel", value=f"<#{starboard_channel_id}>", inline=True)
        else:
            embed.add_field(name="Starboard Channel", value="Not set", inline=True)

        embed.set_footer(text=f"Guild ID: {ctx.guild.id}")
        await ctx.send(embed=embed)


    @commands.Cog.listener()
    async def on_message(self, message):
        """Listen for Poketwo catch messages"""
        # Only process messages from Poketwo
        if message.author.id != 716390085896962058:
            return

        catch_data = None

        # Check for MissingNo. catch (most specific first)
        if "MissingNo." in message.content:
            catch_data = self.parse_poketwo_missingno_message(message.content)

        # Check if it's a catch message
        elif message.content.startswith("Congratulations"):
            catch_data = self.parse_poketwo_catch_message(message.content)

        if not catch_data:
            return

        # Check if this catch is worthy of starboard
        is_shiny = catch_data['is_shiny']
        is_gigantamax = catch_data['is_gigantamax']
        iv = catch_data['iv']
        message_type = catch_data.get('message_type', 'catch')

        # MissingNo. always goes to starboard
        if message_type == 'missingno':
            await self.send_to_starboard_channels(message.guild, catch_data, message)
        else:
            # For catches, check criteria
            # Convert IV string to float for comparison, but keep original string for display
            iv_value = None
            if iv != "Hidden" and iv != "???":
                try:
                    iv_value = float(iv)
                except ValueError:
                    iv_value = None

            if is_shiny or is_gigantamax or (iv_value is not None and (iv_value >= 90 or iv_value <= 10)):
                await self.send_to_starboard_channels(message.guild, catch_data, message)

async def setup(bot):
    await bot.add_cog(Starboard(bot))
