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
LOCK_ROOMS_FOR_NIGHT = True # The bot needs the "Manage Roles" permission for that
LOCK_ROOMS_FOR_PRIVACY = True # The bot needs the "Manage Roles" permission for that
DEFAULT_GAME_NAME = 'Active'

class Game:
  _byCat = {}

  def __init__(self, name, cat, storyteller):
    self.name = name
    self.cat = cat
    self.control_channel = None
    self.storyteller = storyteller
    self.player_role = cat.guild.default_role
    self.default_role = cat.guild.default_role
    self.private_rooms = {}
    Game._byCat[cat] = self

  def fromCat(message):
    cat = message.channel.category
    game = Game._byCat.get(cat, None)
    if game is None:
      # This should happen if and only if the Bot was restarted after setup
      game = Game(DEFAULT_GAME_NAME, cat, message.author)
      game.control_channel = message.channel
    return game

  async def setup(self):
    # Create a private "#control" channel for the storyteller and the bot
    secret_overwrites = {
      self.default_role: discord.PermissionOverwrite(read_messages=False),
      client.user: discord.PermissionOverwrite(read_messages=True),
      self.storyteller: discord.PermissionOverwrite(read_messages=True),
    }
    self.control_channel = await self.cat.create_text_channel('control', overwrites=secret_overwrites)
    await self.cat.create_text_channel('general')
    # Always allow the storyteller to join rooms and move members
    public_overwrites = {
      client.user: discord.PermissionOverwrite(view_channel=True, connect=True, move_members=True),
      self.storyteller: discord.PermissionOverwrite(view_channel=True, connect=True, move_members=True),
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

async def gather(message):
  # Gather all players back into the lobby.
  # Good to break up private discussions and get people to vote.
  await message.channel.send('Gathering up stragglers')
  stragglers = []
  lobby = None
  for room in message.channel.category.voice_channels:
    if room.name == LOBBY:
      lobby = room
    else:
      stragglers += room.members
  if len(stragglers) == 0:
    await message.channel.send('No stragglers found')
  else:
    for player in stragglers:
      # Server mute and move the player. The server mute is there to protect a player from
      # babbling something out while being transferred.
      await player.edit(mute=True, voice_channel=lobby)
    await message.channel.send(f'{len(stragglers)} stragglers gathered ...')
    await asyncio.sleep(GATHER_MUTE_TIME) # wait a second before unmuting
    for player in stragglers:
      await player.edit(mute=False)
    await message.channel.send('... and unmuted')
  await lock_rooms(message.channel.category, ROOMS, message.guild.default_role)

async def night(message):
  await message.channel.send('Moving players into private rooms for night time')
  cat = message.channel.category
  players = []
  private_rooms = {}
  for room in cat.voice_channels:
    players += room.members
    if room.name.startswith(PRIVATE_ROOM_PREFIX):
      name_minus_prefix = room.name[len(PRIVATE_ROOM_PREFIX):]
      private_rooms[name_minus_prefix] = room
  for player in players:
    room = private_rooms.get(player.name, None)
    if room is None:
      secret_overwrites = {
        message.guild.default_role: discord.PermissionOverwrite(view_channel=False, connect=False),
        message.author: discord.PermissionOverwrite(view_channel=True, connect=True, move_members=True),
        player: discord.PermissionOverwrite(view_channel=True, connect=True),
        client.user: discord.PermissionOverwrite(view_channel=True, connect=True, move_members=True),
      }
      room = await cat.create_voice_channel(PRIVATE_ROOM_PREFIX + player.name, overwrites=secret_overwrites)
    await player.move_to(room)
  await lock_rooms(cat, ROOMS + [LOBBY], message.guild.default_role)
  await message.channel.send('Done')

async def lock_rooms(cat, rooms_to_lock, default_role, can_access=False):
  if LOCK_ROOMS_FOR_NIGHT:
    for room in cat.voice_channels:
      if room.name in rooms_to_lock:
        await room.set_permissions(default_role, connect=can_access)

async def unlock_rooms(cat, rooms_to_unlock, default_role):
  await lock_rooms(cat, rooms_to_unlock, default_role, can_access=True)

async def day(message):
  await message.channel.send('Moving players back into the lobby and unlocking rooms')
  cat = message.channel.category
  lobby = discord.utils.get(cat.voice_channels, name=LOBBY)
  await unlock_rooms(cat, ROOMS + [LOBBY], message.guild.default_role)
  for room in cat.voice_channels:
    for player in room.members:
      await player.move_to(lobby)
  await message.channel.send('Done')

async def setup(message):
  is_authorized = ((message.guild.owner_id == message.author.id) or
    (discord.utils.get(message.author.roles, name=STORYTELLER_ROLE) is not None))
  if not is_authorized:
    await message.channel.send('Only the owner or a BotCH Storyteller can create a new game')
    return
  await message.channel.send(f'Setting up structure for {str(message.guild)}')
  cat = await message.guild.create_category(CATEGORY)
  game = Game(DEFAULT_GAME_NAME, cat, message.author)
  await game.setup()
  await message.channel.send('Created category ' + str(cat))

@client.event
async def on_ready():
  print(f'{client.user} has connected to Discord!')

@client.event
async def on_message(message):
  if message.author == client.user:
    return

  if message.content == '!BotCH setup':
    await setup(message)

  if message.channel.category.name == CATEGORY and message.channel.name == 'control':
    game = Game.fromCat(message)
    if message.content == '!cleanup':
      await game.cleanup()
    if message.content == '!gather':
      await gather(message)
    if message.content == '!night':
      await night(message)
    if message.content == '!day':
      await day(message)

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
