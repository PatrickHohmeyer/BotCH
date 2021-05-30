import os
import time

import discord
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

client = discord.Client()
CATEGORY = 'Blood on the Clocktower'
ROOMS = ['Ballroom', 'Billiard Room', 'Conservatory', 'Dining Room', 'Hall', 'Kitchen', 'Library', 'Lounge', 'Study']

@client.event
async def on_ready():
  print(f'{client.user} has connected to Discord!')

@client.event
async def on_message(message):
  if message.author == client.user:
    return

  print(f'Message in channel {message.channel.name}, category {message.channel.category.name}!')
  if message.content == '#BotCH setup':
    print(f'Setup for {message.guild}!')
    await message.channel.send('Setting up structure for ' + str(message.guild))
    cat = await message.guild.create_category(CATEGORY)
    await cat.create_text_channel('general')
    secret_overwrites = {
      message.guild.default_role: discord.PermissionOverwrite(read_messages=False),
      client.user: discord.PermissionOverwrite(read_messages=True),
      message.author: discord.PermissionOverwrite(read_messages=True)
    }
    await cat.create_text_channel('control', overwrites=secret_overwrites)
    await cat.create_voice_channel('Lobby')
    for room in ROOMS:
      await cat.create_voice_channel(room)
    await message.channel.send('Created category ' + str(cat))

  if message.channel.category.name == CATEGORY and message.channel.name == 'control':
    if message.content == '#cleanup':
      await message.channel.send('Cleaning the game up')
      cat = message.channel.category
      for room in cat.channels:
        await room.delete()
      await cat.delete()
    
    if message.content == '#gather':
      await message.channel.send('Gathering up stragglers')
      stragglers = []
      lobby = None
      for room in message.channel.category.voice_channels:
        if room.name == 'Lobby':
          print(f'Found the lobby with members {room.members}')
          lobby = room
        else:
          print(f'Found room {room.name} with members {room.members}')
          if len(room.members) != 0:            
            stragglers += room.members
      if len(stragglers) == 0:
        await message.channel.send('No stragglers found')
      else:
        await message.channel.send('Found ' + str(len(room.members)) + ' stragglers in room ' + room.name)
        for player in stragglers:
          await player.edit(mute=True, voice_channel=lobby, reason = 'BotCH: gathering players back into Lobby')
        await message.channel.send(f'{len(stragglers)} stragglers gathered ...')
        time.sleep(1)
        print(f'Found stragglers {stragglers}')
        for player in stragglers:
          await player.edit(mute=False, reason = 'BotCH: gathering players back into Lobby')
        await message.channel.send('... and unmuted')

    if message.content == '#night':

    if message.content == '#day':

client.run(TOKEN)
