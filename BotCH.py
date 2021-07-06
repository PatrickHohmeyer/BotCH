import os
import asyncio

import discord
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

client = discord.Client()
CATEGORY = 'Blood on the Clocktower'
LOBBY = 'Lobby'
ROOMS = ['Ballroom', 'Billiard Room', 'Conservatory', 'Dining Room', 'Hall', 'Kitchen', 'Library', 'Lounge', 'Study']
PRIVATE_ROOM_PREFIX = '_BotCH_private_'
GATHER_MUTE_TIME = 1
STORYTELLER_ROLE = 'BotCH Storyteller'
ACTIVE_STORYTELLER_ROLE = 'BotCH Active Storyteller'
LOCK_ROOMS_FOR_NIGHT = True # The bot needs the "Manage Roles" permission for that
LOCK_ROOMS_FOR_PRIVACY = True # The bot needs the "Manage Roles" permission for that
DEFAULT_GAME_NAME = 'Active'

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
    await self.cat.create_text_channel('general')
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
    self.storyteller_role.delete()

  async def gather(self):
    # Gather all players back into the lobby.
    # Good to break up private discussions and get people to vote.
    await self.control_channel.send('Gathering up stragglers')
    stragglers = []
    lobby = None
    for room in self.cat.voice_channels:
      if room.name == LOBBY:
        lobby = room
      else:
        stragglers += room.members
    if len(stragglers) == 0:
      await self.control_channel.send('No stragglers found')
    else:
      for player in stragglers:
        # Server mute and move the player. The server mute is there to protect a player from
        # babbling something out while being transferred.
        await player.edit(mute=True, voice_channel=lobby)
      await self.control_channel.send(f'{len(stragglers)} stragglers gathered ...')
      await asyncio.sleep(GATHER_MUTE_TIME) # wait a second before unmuting
      for player in stragglers:
        await player.edit(mute=False)
      await self.control_channel.send('... and unmuted')
    await self.lock_rooms(ROOMS)

  async def night(self):
    await self.control_channel.send('Moving players into private rooms for night time')
    players = []
    private_rooms = {}
    for room in self.cat.voice_channels:
      players += room.members
      if room.name.startswith(PRIVATE_ROOM_PREFIX):
        name_minus_prefix = room.name[len(PRIVATE_ROOM_PREFIX):]
        private_rooms[name_minus_prefix] = room
    for player in players:
      room = private_rooms.get(player.name, None)
      if room is None:
        secret_overwrites = {
          self.default_role: discord.PermissionOverwrite(view_channel=False, connect=False),
          self.storyteller_role: discord.PermissionOverwrite(view_channel=True, connect=True, move_members=True),
          player: discord.PermissionOverwrite(view_channel=True, connect=True),
          client.user: discord.PermissionOverwrite(view_channel=True, connect=True, move_members=True),
        }
        room = await self.cat.create_voice_channel(PRIVATE_ROOM_PREFIX + player.name, overwrites=secret_overwrites)
      await player.move_to(room)
    await self.lock_rooms(ROOMS + [LOBBY])
    await self.control_channel.send('Done')

  async def day(self):
    await self.control_channel.send('Moving players back into the lobby and unlocking rooms')
    lobby = discord.utils.get(self.cat.voice_channels, name=LOBBY)
    await self.unlock_rooms(ROOMS + [LOBBY])
    for room in self.cat.voice_channels:
      for player in room.members:
        await player.move_to(lobby)
    await self.control_channel.send('Done')

  async def lock_rooms(self, rooms_to_lock):
    if LOCK_ROOMS_FOR_NIGHT:
      for room in self.cat.voice_channels:
        if room.name in rooms_to_lock:
          await room.set_permissions(self.default_role, connect=False)

  async def unlock_rooms(self, rooms_to_unlock):
    for room in self.cat.voice_channels:
      if room.name in rooms_to_unlock:
        await room.set_permissions(self.default_role, connect=True)

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

async def lock_public_room_for_privacy(room, default_role):
  await asyncio.sleep(5)
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
  if before.channel and before.channel.category and before.channel.category.name == CATEGORY:
    if before.channel.name in ROOMS and not before.channel.members:
      await unlock_empty_room(before.channel, member.guild.default_role)

client.run(TOKEN)
