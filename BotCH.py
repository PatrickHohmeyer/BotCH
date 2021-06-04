import os
import time

import discord
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

client = discord.Client()
CATEGORY = 'Blood on the Clocktower'
ROOMS = ['Ballroom', 'Billiard Room', 'Conservatory', 'Dining Room', 'Hall', 'Kitchen', 'Library', 'Lounge', 'Study']
PRIVATE_ROOM_PREFIX = '_BotCH_private_'
STORYTELLER_ROLE = 'BotCH Storyteller'

@client.event
async def on_ready():
  print(f'{client.user} has connected to Discord!')

@client.event
async def on_message(message):
  if message.author == client.user:
    return

  if message.content == '!BotCH setup':
    is_authorized = ((message.guild.owner_id == message.author.id) or
      (discord.utils.get(message.author.roles, name=STORYTELLER_ROLE) is not None))
    if not is_authorized:
      await message.channel.send('Only the owner or a BotCH Storyteller can create a new game')
      return
    await message.channel.send(f'Setting up structure for {str(message.guild)}')
    cat = await message.guild.create_category(CATEGORY)
    # Create a private "#control" channel for the storyteller and the bot
    secret_overwrites = {
      message.guild.default_role: discord.PermissionOverwrite(read_messages=False),
      client.user: discord.PermissionOverwrite(read_messages=True),
      message.author: discord.PermissionOverwrite(read_messages=True),
    }
    await cat.create_text_channel('control', overwrites=secret_overwrites)
    await cat.create_text_channel('general')
    await cat.create_voice_channel('Lobby')
    for room in ROOMS:
      await cat.create_voice_channel(room)
    await message.channel.send('Created category ' + str(cat))

  if message.channel.category.name == CATEGORY and message.channel.name == 'control':
    if message.content == '!cleanup':
      await message.channel.send('Cleaning the game up')
      cat = message.channel.category
      for room in cat.channels:
        await room.delete()
      await cat.delete()
    
    if message.content == '!gather':
      # Gather all players back into the lobby.
      # Good to break up private discussions and get people to vote.
      await message.channel.send('Gathering up stragglers')
      stragglers = []
      lobby = None
      for room in message.channel.category.voice_channels:
        if room.name == 'Lobby':
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
        time.sleep(1) # wait a second before unmuting
        for player in stragglers:
          await player.edit(mute=False)
        await message.channel.send('... and unmuted')

    if message.content == '!night':
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
            message.author: discord.PermissionOverwrite(view_channel=True, connect=True),
            player: discord.PermissionOverwrite(view_channel=True, connect=True),
          }
          room = await cat.create_voice_channel(PRIVATE_ROOM_PREFIX + player.name, overwrites=secret_overwrites)
        await player.move_to(room)
      await message.channel.send('Done')

    if message.content == '!day':
      await message.channel.send('Moving players back into the lobby and unlocking rooms')
      cat = message.channel.category
      lobby = discord.utils.get(cat.voice_channels, name='Lobby')
      for room in cat.voice_channels:
        for player in room.members:
          await player.move_to(lobby)

client.run(TOKEN)
