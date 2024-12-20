import os
import asyncio
from typing import Literal
from datetime import datetime, date, time, timedelta
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
DEPUTY_TOKEN = [os.getenv('DEPUTY1_TOKEN'), os.getenv('DEPUTY2_TOKEN')]
GUILD_ID = int(os.getenv('GUILD_ID'))
intents = discord.Intents.default()
intents.guild_reactions = True
intents.guild_messages = True
intents.integrations = True

# Uncomment to enable debugging
# discord.utils.setup_logging()

class MyClient(discord.Client):
  def __init__(self, *, intents: discord.Intents):
    super().__init__(intents=intents)
    self.botch_group = app_commands.Group(
        name="botch", description='Commands for BotCH')
    self.tree = app_commands.CommandTree(self)

  async def setup_hook(self):
    my_guild = discord.Object(id=GUILD_ID) 
    self.tree.add_command(self.botch_group, guild=my_guild)
    await self.tree.sync(guild=my_guild)

client = MyClient(intents = intents)

# Names for various Discord entities
CATEGORY = 'Blood on the Clocktower'
LOBBY = 'Lobby'
ROOMS = ['Ballroom', 'Billiard Room', 'Conservatory', 'Dining Room', 'Hall', 'Kitchen', 'Library', 'Lounge', 'Study']
PRIVATE_ROOM_PREFIX = '_BotCH_private_'
STORYTELLER_ROLE = 'BotCH Storyteller'
ACTIVE_STORYTELLER_ROLE = 'BotCH Active Storyteller'

# Time to mute players when dragging them into the Lobby. Recommended to leave at 1.
GATHER_MUTE_TIME = 1

# Time to mute players when clicking SHUSH
SHUSH_MUTE_TIME = 10

# Whether to lock the public rooms during dusk/night.
# This will e.g. prevent players from jumping into the lobby early.
LOCK_ROOMS_FOR_NIGHT = False # The bot needs the "Manage Roles" permission for that

# Whether to lock the side rooms after players joined. This will prevent a third party to drop into
# a private conversation - we had some problems with curious players doing just that. Usually this
# should be governed by social conventions instead, but if you want to use technology to enforce
# them, this setting is for you.
# The rooms will be unlocked after the last player left.
# The Storyteller is not affected by this and can always join rooms.
LOCK_ROOMS_FOR_PRIVACY = False # The bot needs the "Manage Roles" permission for that
# How long to wait after the first player joined to lock the room
LOCK_FOR_PRIVACY_TIME = 5

# How long to display the Bots messages before deleting them.
BOT_MESSAGES_DISPLAY_TIME = 10

# Work in progress to allow multiple games on the same server.
DEFAULT_GAME_NAME = 'Active'

DUSK_EMOJI = '🌆'
NIGHT_EMOJI = '🌃'
MORNING_EMOJI = '🌇'
SHUSH_EMOJI = '🤫'

OK_EMOJI = '👍'
LATE_EMOJI = '⏲️'
MAYBE_EMOJI = '🤔'
NO_EMOJI = '🙁'

deputy_players = []
DEPUTY_DIVIDER = 1

current_deputy = 0
async def deputized_move(player, room):
  global deputy_players, current_deputy
  current_deputy = (current_deputy + 1) % DEPUTY_DIVIDER
  if (current_deputy != 0) and deputy_players[current_deputy - 1] and deputy_players[current_deputy - 1][player.id]:
    await deputy_players[current_deputy - 1][player.id].move_to(room)
  else:
    await player.move_to(room)

async def deputized_move_and_mute(player, room):
  global deputy_players, current_deputy
  current_deputy = (current_deputy + 1) % DEPUTY_DIVIDER
  if (current_deputy != 0) and deputy_players[current_deputy - 1] and deputy_players[current_deputy - 1][player.id]:
    await deputy_players[current_deputy - 1][player.id].edit(mute=True, voice_channel=room)
  else:
    await player.edit(mute=True, voice_channel=room)

async def send_temp_message(channel, text):
  msg = await(channel.send(text))
  await msg.delete(delay=BOT_MESSAGES_DISPLAY_TIME)

async def send_temp_response(interaction, text):
  await interaction.response.send_message(
      content=text, ephemeral=True, delete_after=BOT_MESSAGES_DISPLAY_TIME)

class Game:
  _byCat = {}

  def __init__(self, name, cat):
    self.name = name
    self.cat = cat
    self.control_channel = None
    self.storyteller_role = discord.utils.get(cat.guild.roles, name=ACTIVE_STORYTELLER_ROLE)
    self.default_role = cat.guild.default_role
    self.private_rooms = {}
    Game._byCat[cat] = self

  def fromCat(cat):
    game = Game._byCat.get(cat, None)
    if game is None:
      # This should happen if and only if the Bot was restarted after setup
      game = Game(DEFAULT_GAME_NAME, cat)
      game.control_channel = discord.utils.get(cat.guild.text_channels, name='control')
    return game

  async def setup(self):
    # Create a private "#control" channel for the storyteller and the bot
    secret_overwrites = {
      self.default_role: discord.PermissionOverwrite(read_messages=False),
      client.user: discord.PermissionOverwrite(read_messages=True),
      self.storyteller_role: discord.PermissionOverwrite(read_messages=True),
    }
    self.control_channel = await self.cat.create_text_channel('control', overwrites=secret_overwrites)
    msg = await self.control_channel.send('Hi, please click icons to interact with the bot.')
    await msg.add_reaction(DUSK_EMOJI)
    await msg.add_reaction(NIGHT_EMOJI)
    await msg.add_reaction(MORNING_EMOJI)
    await msg.add_reaction(SHUSH_EMOJI)

    await self.cat.create_text_channel('game-chat')
    # Always allow the storyteller to join rooms and move members
    public_overwrites = {
      client.user: discord.PermissionOverwrite(view_channel=True, connect=True, move_members=True),
      self.storyteller_role: discord.PermissionOverwrite(view_channel=True, connect=True, move_members=True),
    }
    await self.cat.create_voice_channel(LOBBY, overwrites=public_overwrites)
    for room in ROOMS:
      await self.cat.create_voice_channel(room, overwrites=public_overwrites)

  async def cleanup(self, sendfx):
    await sendfx('Cleaning the game up')
    for room in self.cat.channels:
      await room.delete()
    del Game._byCat[self.cat]
    await self.cat.delete()
    # And finally remove the active storyteller role
    await self.storyteller_role.delete()

  async def self_deleting_message(self, text):
    await send_temp_message(self.control_channel, text)

  async def gather(self):
    # Gather all players back into the lobby.
    # Good to break up private discussions and get people to vote.
    await self.self_deleting_message('Gathering up stragglers')
    stragglers = []
    lobby = None
    for room in self.cat.voice_channels:
      if room.name == LOBBY:
        lobby = room
      else:
        stragglers += room.members
    if len(stragglers) == 0:
      await self.self_deleting_message('No stragglers found')
    else:
      for player in stragglers:
        # Server mute and move the player. The server mute is there to protect a player from
        # babbling something out while being transferred.
        await deputized_move_and_mute(player, lobby)
      await self.self_deleting_message(f'{len(stragglers)} stragglers gathered ...')
      await asyncio.sleep(GATHER_MUTE_TIME) # wait a second before unmuting
      for player in stragglers:
        await player.edit(mute=False)
      await self.self_deleting_message('... and unmuted')
    await self.lock_rooms(ROOMS)

  async def night(self):
    await self.self_deleting_message('Moving players into private rooms for night time')
    players = []
    for room in self.cat.voice_channels:
      players += room.members
    for player in players:
      room = await self.ensurePrivateRoom(player)
      await deputized_move(player, room)
    await self.lock_rooms(ROOMS + [LOBBY])
    await self.self_deleting_message('Done')

  async def day(self):
    await self.self_deleting_message('Moving players back into the lobby and unlocking rooms')
    lobby = discord.utils.get(self.cat.voice_channels, name=LOBBY)
    for room in self.cat.voice_channels:
      for player in room.members:
        await deputized_move(player, lobby)
    await self.unlock_rooms(ROOMS + [LOBBY])
    await self.self_deleting_message('Done')

  async def shush(self):
    lobby = discord.utils.get(self.cat.voice_channels, name=LOBBY)
    muted_players = lobby.members
    for player in muted_players:
      if not player in self.storyteller_role.members:
        await player.edit(mute=True)
    await self.self_deleting_message(f'Muted lobby for {SHUSH_MUTE_TIME} seconds ...')
    await asyncio.sleep(SHUSH_MUTE_TIME)
    for player in muted_players:
      await player.edit(mute=False)
    await self.self_deleting_message('... and unmuted')

  async def lock_rooms(self, rooms_to_lock):
    if LOCK_ROOMS_FOR_NIGHT:
      for room in self.cat.voice_channels:
        if room.name in rooms_to_lock:
          await room.set_permissions(self.default_role, connect=False)

  async def unlock_rooms(self, rooms_to_unlock):
    for room in self.cat.voice_channels:
      if room.name in rooms_to_unlock:
        await room.set_permissions(self.default_role, connect=True)
  
  # Creating rooms is severely throttled on Discord and we ran into problems when creating all the
  # private rooms in the first night. So now we create them when we see a player join any voice
  # channel under the game's category. (Usually when they join the Lobby the first time.)
  # And then, we only need to move people at night and not create rooms for them.
  async def ensurePrivateRoom(self, player):
    room_name = PRIVATE_ROOM_PREFIX + player.name
    room = discord.utils.get(self.cat.voice_channels, name=room_name)
    if room is None:
      # Nobody can even see the room, except for the Bot, the Storyteller and the player who's room it is.
      secret_overwrites = {
        self.default_role: discord.PermissionOverwrite(view_channel=False, connect=False),
        self.storyteller_role: discord.PermissionOverwrite(view_channel=True, connect=True, move_members=True),
        player: discord.PermissionOverwrite(view_channel=True, connect=True),
        client.user: discord.PermissionOverwrite(view_channel=True, connect=True, move_members=True),
      }
      room = await self.cat.create_voice_channel(room_name, overwrites=secret_overwrites)
    return room
      

def isInBotCHCategory(channel):
  return channel and channel.category and channel.category.name == CATEGORY

def isControlChannel(channel):
  return isInBotCHCategory(channel) and channel.name == 'control'

async def setup(guild, author, sendfx):
  is_authorized = ((guild.owner_id == author.id) or
    (discord.utils.get(author.roles, name=STORYTELLER_ROLE) is not None))
  if not is_authorized:
    await sendfx('Only the owner or a BotCH Storyteller can create a new game')
    return
  if CATEGORY in guild.categories:
    await sendfx(f'Category {CATEGORY} already exists')
    return
  await sendfx(f'Setting up structure for {str(guild)}')
  await guild.create_role(name=ACTIVE_STORYTELLER_ROLE, colour=discord.Colour.green())
  cat = await guild.create_category(CATEGORY)
  game = Game(DEFAULT_GAME_NAME, cat)
  await author.add_roles(game.storyteller_role)
  await game.setup()
  await sendfx(f'Created category {str(cat)}')

async def assureStorytellerRoles(guild):
  if discord.utils.get(guild.roles, name=STORYTELLER_ROLE) is None:
    await guild.create_role(name=STORYTELLER_ROLE)

@client.event
async def on_ready():
  print(f'{client.user} has connected to Discord!')
  for g in client.guilds:
    await assureStorytellerRoles(g)

@client.event
async def on_guild_join(guild):
  print(f'{client.user} has joined {guild}!')
  await assureStorytellerRoles(guild)

# We use "raw" reactions in case the bot was restarted since it created the message
@client.event
async def on_raw_reaction_add(payload):
  await on_raw_reaction(payload)

@client.event
async def on_raw_reaction_remove(payload):
  await on_raw_reaction(payload)

async def on_raw_reaction(payload):
  if payload.user_id == client.user.id:
    return

  channel = client.get_channel(payload.channel_id)
  if channel.category.name == CATEGORY and channel.name == 'control':
    game = Game.fromCat(channel.category)
    if payload.emoji.name == DUSK_EMOJI:
      await game.gather()      
    if payload.emoji.name == NIGHT_EMOJI:
      await game.night()
    if payload.emoji.name == MORNING_EMOJI:
      await game.day()
    if payload.emoji.name == SHUSH_EMOJI:
      await game.shush()

async def lock_public_room_for_privacy(room, default_role):
  if LOCK_ROOMS_FOR_PRIVACY:
    await asyncio.sleep(LOCK_FOR_PRIVACY_TIME)
    if room.members:
      await room.set_permissions(default_role, connect=False)

async def unlock_empty_room(room, default_role):
  if not room.members:
    await room.set_permissions(default_role, connect=True)

@client.event
async def on_voice_state_update(member, before, after):
  if after.channel == before.channel:
    return # ignore mute / unmute events and similar things, we only want channel changes

  if isInBotCHCategory(after.channel):
    if (after.channel.name in ROOMS):
      asyncio.create_task(lock_public_room_for_privacy(after.channel, member.guild.default_role))
    game = Game.fromCat(after.channel.category)
    await game.ensurePrivateRoom(member)
  if isInBotCHCategory(before.channel):
    if before.channel.name in ROOMS and not before.channel.members:
      await unlock_empty_room(before.channel, member.guild.default_role)
    game = Game.fromCat(before.channel.category)
    await game.ensurePrivateRoom(member)

@client.botch_group.command(
    name = 'set-storyteller', description = 'This will change the active storyteller.')
@app_commands.describe(new_storyteller="The new storyteller")
async def set_storyteller(
    ctx: discord.Interaction, new_storyteller : discord.Member):
  if isControlChannel(ctx.channel):
    game = Game.fromCat(ctx.channel.category)
    if game.storyteller_role in new_storyteller.roles:
      await send_temp_response(ctx,
        f'Asked to set the storyteller to: {new_storyteller}, but that IS the storyteller')
      return
    if not game.storyteller_role in ctx.author.roles:
      await send_temp_response(ctx, f'You are not the current storyteller!')
      return
    await send_temp_message(ctx.channel, f'Setting storyteller to: {new_storyteller}')
    await new_storyteller.add_roles(game.storyteller_role)
    await ctx.user.remove_roles(game.storyteller_role)
    await send_temp_response(ctx, f'Storyteller change complete!')
  else:
    await send_temp_response(ctx, 'You must send the commands from the control channel.')

@client.botch_group.command(
    name="setup",
    description="Setup the Blood on the Clocktower category and channels.")
async def slash_setup(ctx):
  await setup(ctx.guild, ctx.user, ctx.channel.send) # TODO: use response correctly

@client.botch_group.command(
    name="cleanup",
    description="This will delete the Blood on the Clocktower category and all sub-channels.")
async def slash_cleanup(ctx):
  if isControlChannel(ctx.channel):
    game = Game.fromCat(ctx.channel.category)
    await game.cleanup(ctx.channel.send)
  else:
    await send_temp_response(
        ctx, 'You must send the cleanup command from the control channel.')

BaseOption = Literal['Base editions', 'Teensyville (few)', 'Teensyville (many)', 'Teensyville (TAP)', 'Custom Scripts', 'Empty']
BASE_OPTIONS={
  'Base editions': ['Trouble Brewing', 'Sects & Violets', 'Bad Moon Rising'],
  'Teensyville (few)': ['Trouble Brewing', 'Laissez un Faire', 'No Greater Joy', 'Race to the Bottom'],
  'Teensyville (many)': ['Trouble Brewing', 'Laissez un Faire', 'No Greater Joy', 'Race to the Bottom', 'Miserable Little Pile of Secrets', 'A Lleech of Distrust', 'On Thin Ice (has twins)', 'Spooky Tea', 'Frankenstein''s Mayor'],
  'Teensyville (TAP)': ['Yes, Your Immenence', 'Ikebana!', 'Witness Protection', 'Finding Religion', 'Which Script is This Anyway?', 'High Noon (Easy)', 'High Noon (Hard: +Legion)', 'Mirror Mirror', 'Oh No Jo', 'This is Jeopardy!', 'Beauty and the Beasts', 'Demonic Tutor v3', 'Any Idiot May Juggle', 'Good Luck, Sir'],
  'Custom Scripts': ['Catfishing', 'Deadly Penance Day', 'Hide & Seek', 'Public Executions', 'Tax Fraud'],
  'Empty': []
}

@client.botch_group.command(
    name="poll",
    description="Simple edition poll.")
async def slash_poll(ctx, base_options : BaseOption, more_options : str = ''):
  op = BASE_OPTIONS[base_options].copy()
  if more_options:
    op += more_options.split(',')
  s = 'Poll:\n'
  emoji = 0x1F1E6 # regional_indicator_a, Discord renders this as an A in a blue square
  for o in op:
    s += f'{chr(emoji)} - {o.strip()}\n'
    emoji += 1
  if base_options != 'Base editions' or more_options:
    s += 'See <https://botc-scripts.azurewebsites.net/> for custom scripts.'
  await ctx.response.send_message(s)
  msg = await ctx.original_response()
  emoji = 0x1F1E6
  for o in op:
    await msg.add_reaction(chr(emoji))
    emoji += 1


SCHEDULE_MSG='''
You can also react to this message to indicate "maybe" and "late":
👍 = "I'm in if we get enough people"
⏲️ = "I'm in, but I'll be late"
🤔 = "I might be in but am not sure yet"
🙁 = "I'm out"'''

@client.botch_group.command(
    name="schedule",
    description="Create an event for Blood on the Clocktower")
async def slash_schedule(ctx):
  is_authorized = ((ctx.guild.owner_id == ctx.user.id) or
    (discord.utils.get(ctx.user.roles, name=STORYTELLER_ROLE) is not None))
  if not is_authorized:
    await send_temp_response(ctx, 'You cannot create events with this bot')
    return
  d = date.today()
  delta = 6 - d.weekday() if d.weekday() != 6 else 7
  d += timedelta(days=delta)
  event_time = datetime.combine(d, time(19,0,0,0, tzinfo=ZoneInfo("US/Eastern")))
  cat = discord.utils.get(ctx.guild.categories, name=CATEGORY)
  event = await ctx.guild.create_scheduled_event(
      name = 'Blood on the Clocktower',
      description = '',
      channel = discord.utils.get(cat.voice_channels, name=LOBBY),
      start_time = event_time,
      privacy_level = discord.PrivacyLevel.guild_only)
  scheduled_channel = discord.utils.get(ctx.guild.text_channels, name='scheduling')
  msg = await scheduled_channel.send(
      f'@everyone Clocktower on Sunday\n{event.url}\n{SCHEDULE_MSG}')
  await msg.add_reaction(OK_EMOJI)
  await msg.add_reaction(LATE_EMOJI)
  await msg.add_reaction(MAYBE_EMOJI)
  await msg.add_reaction(NO_EMOJI)
  await send_temp_response(ctx, f'Scheduled {event.url}')


loop = asyncio.get_event_loop()
loop.create_task(client.start(TOKEN))

def create_deputy(dt):
  global loop, deputy_players, DEPUTY_DIVIDER
  d = discord.Client(intents=discord.Intents.default())
  d_players = {}
  deputy_players.append(d_players)
  DEPUTY_DIVIDER += 1

  @d.event
  async def on_ready():
    print(f'{d.user} has connected to Discord!')

  @d.event
  async def on_voice_state_update(member, before, after):
    if after.channel == before.channel:
      return # ignore mute / unmute events and similar things, we only want channel changes

    if isInBotCHCategory(after.channel) or isInBotCHCategory(before.channel):
      # Keep track of the players - this allows us to use the deputy for moves
      d_players[member.id] = member
  loop.create_task(d.start(dt))

for dt in DEPUTY_TOKEN:
  create_deputy(dt)

loop.run_forever()
