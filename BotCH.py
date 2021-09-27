import os
import asyncio

import discord
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
intents = discord.Intents.default()
intents.guild_reactions = True
intents.guild_messages = True

client = discord.Client(intents = intents)
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

  async def cleanup(self):
    await self.control_channel.send('Cleaning the game up')
    for room in self.cat.channels:
      await room.delete()
    del Game._byCat[self.cat]
    await self.cat.delete()
    # And finally remove the active storyteller role
    await self.storyteller_role.delete()

  async def self_deleting_message(self, text):
    msg = await(self.control_channel.send(text))
    await msg.delete(delay=BOT_MESSAGES_DISPLAY_TIME)

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
        await player.edit(mute=True, voice_channel=lobby)
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
      await player.move_to(room)
    await self.lock_rooms(ROOMS + [LOBBY])
    await self.self_deleting_message('Done')

  async def day(self):
    await self.self_deleting_message('Moving players back into the lobby and unlocking rooms')
    lobby = discord.utils.get(self.cat.voice_channels, name=LOBBY)
    for room in self.cat.voice_channels:
      for player in room.members:
        await player.move_to(lobby)
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
      

async def setup(message):
  is_authorized = ((message.guild.owner_id == message.author.id) or
    (discord.utils.get(message.author.roles, name=STORYTELLER_ROLE) is not None))
  if not is_authorized:
    await message.channel.send('Only the owner or a BotCH Storyteller can create a new game')
    return
  await message.channel.send(f'Setting up structure for {str(message.guild)}')
  await message.guild.create_role(name=ACTIVE_STORYTELLER_ROLE, colour=discord.Colour.green())
  cat = await message.guild.create_category(CATEGORY)
  game = Game(DEFAULT_GAME_NAME, cat)
  await message.author.add_roles(game.storyteller_role)
  await game.setup()
  await message.channel.send('Created category ' + str(cat))

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

@client.event
async def on_message(message):
  if message.author == client.user:
    return

  if message.content == '!BotCH setup':
    await setup(message)

  if message.channel.category.name == CATEGORY and message.channel.name == 'control':
    game = Game.fromCat(message.channel.category)
    if message.content == '!cleanup':
      await game.cleanup()
    if message.content == '!gather':
      await game.gather()
    if message.content == '!night':
      await game.night()
    if message.content == '!day':
      await game.day()

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
  await asyncio.sleep(LOCK_FOR_PRIVACY_TIME)
  if room.members:
    await room.set_permissions(default_role, connect=False)

async def unlock_empty_room(room, default_role):
  if not room.members:
    await room.set_permissions(default_role, connect=True)

@client.event
async def on_voice_state_update(member, before, after):
  if not LOCK_ROOMS_FOR_PRIVACY:
    return

  if after.channel == before.channel:
    return # ignore mute / unmute events and similar things, we only want channel changes

  if after.channel and after.channel.category and after.channel.category.name == CATEGORY:
    if (after.channel.name in ROOMS):
      asyncio.create_task(lock_public_room_for_privacy(after.channel, member.guild.default_role))
    game = Game.fromCat(after.channel.category)
    await game.ensurePrivateRoom(member)
  if before.channel and before.channel.category and before.channel.category.name == CATEGORY:
    if before.channel.name in ROOMS and not before.channel.members:
      await unlock_empty_room(before.channel, member.guild.default_role)
    game = Game.fromCat(before.channel.category)
    await game.ensurePrivateRoom(member)

client.run(TOKEN)
