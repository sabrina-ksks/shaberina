import asyncio
import discord
from discord.ext import commands
from dotenv import load_dotenv
import os
from copy import deepcopy

from utils import *
from postgres import Postgres
from tts import TTS

from logging import getLogger, StreamHandler, Formatter, DEBUG, INFO

logger = getLogger(__name__)
logger.setLevel(DEBUG)
logger.propagate = False
hdlr = StreamHandler()
hdlr.setLevel(DEBUG)
fmt = Formatter(fmt='[{asctime}][{name}][{funcName}][{levelname}] {message}', datefmt='%Y-%m-%d %H:%M:%S' ,style='{')
hdlr.setFormatter(fmt)
logger.addHandler(hdlr)


load_dotenv()
TOKEN = os.environ['TOKEN']
DATABASE_URL = os.environ['DATABASE_URL']

pg = Postgres(DATABASE_URL)
tts = TTS()

default_prefix = pg.get_default('guild')['prefix']

async def fetch_prefix(bot:commands.Bot, message:discord.Message) -> str:
    if message.guild is None:
        return default_prefix
    else:
        guild_conf = await pg.fetch(message.guild)
        return guild_conf['prefix']

bot = commands.Bot(command_prefix=fetch_prefix, help_command=None)

########################################################################################################
#ここから内部関数の定義

async def is_target_ch(ctx:commands.Context) -> bool:
    guild_conf = await pg.fetch(ctx.guild)
    if (guild_conf['target_ch'] == 'all') or (guild_conf['target_ch'] == str(ctx.channel.id)):
        return True
    else:
        #helpを操作チャンネル以外から使用した場合のみ出力
        #　Noneが返ってくるのはon_message内のhelpでの判定時
        if ctx.command in {None, help}:
            await ctx.send(f'<#{guild_conf["target_ch"]}>から操作してください．')
        return False


async def play_wav(wavpath:str, voice_client:discord.VoiceClient) -> None:
    try:
        source = discord.FFmpegPCMAudio(wavpath, before_options='-channel_layout mono')
        while voice_client.is_playing():
            await asyncio.sleep(1)
        voice_client.play(source)
    except (discord.ClientException, AttributeError):
        pass
    except Exception as error:
        logger.error(f'{error.__class__.__name__}: {error}')


async def read_text(text:str, voice_conf:dict, voice_client:discord.VoiceClient) -> None:
    if (voice_client is None) or (text == ''):
        return

    wavpath = None
    try:
        wavpath = tts.synthesize(text, **voice_conf)
        if (wavpath is not None) and os.path.exists(wavpath):
            await play_wav(wavpath, voice_client)
            while voice_client.is_playing():
                await asyncio.sleep(1)
    except (discord.ClientException, AttributeError):
        pass
    except Exception as error:
        logger.error(f'{error.__class__.__name__}: {error}')
    finally:
        if (wavpath is not None) and os.path.exists(wavpath):
            os.remove(wavpath)


async def send_notify(guild_name:str, ch:discord.TextChannel, embed:discord.Embed) -> bool:
    done = False
    try:
        await ch.send(embed=embed)
        done = True
    except Exception:
        logger.error(f'サーバー「{guild_name}」へのお知らせの送信に失敗しました．')
    return done


#ここまで内部関数の定義
########################################################################################################
#ここからbotの挙動

@bot.event
async def on_ready():
    logger.info(f'{bot.user.name}のログインに成功しました．')
    await pg.connect()
    presence = f'{default_prefix}help | 0/{len(bot.guilds)}サーバー'
    await bot.change_presence(activity=discord.Game(name=presence))


@bot.event
async def on_guild_join(guild:discord.Guild):
    logger.info(f'サーバー「{guild.name}」に招待されました．')
    presence = f'{default_prefix}help | {len(bot.voice_clients)}/{len(bot.guilds)}サーバー'
    await bot.change_presence(activity=discord.Game(name=presence))
    try:
        await guild.system_channel.send(embed=invited_embed(default_prefix))
    except Exception:
        pass


@bot.event
async def on_guild_remove(guild:discord.Guild):
    logger.info(f'サーバー「{guild.name}」からキックされました．')
    presence = f'{default_prefix}help | {len(bot.voice_clients)}/{len(bot.guilds)}サーバー'
    await bot.change_presence(activity=discord.Game(name=presence))


#botのオーナーのみ使用可
@bot.command(aliases=['sd'])
@commands.is_owner()
async def shutdown(ctx:commands.Context, option:str=None):
    if option == '-y':
        await ctx.send('メンテナンスのためしばらく眠ります．おやすみなさい．')
        await pg.disconnect()
        await bot.close()
        logger.info(f'{bot.user.name}をシャットダウンしました．')
    else:
        await ctx.send(f'{bot.user.name}をシャットダウンしますか？(y/n)')
        def check(m:discord.Message) -> bool:
            return (m.author == ctx.author) and (m.content in {'y', 'n'})
        msg = await bot.wait_for('message', check=check)
        if msg.content == 'y':
            await ctx.send('メンテナンスのためしばらく眠ります．おやすみなさい．')
            await pg.disconnect()
            await bot.close()
            logger.info(f'{bot.user.name}をシャットダウンしました．')
        else:
            await ctx.send('シャットダウンを中止しました．')


#botのオーナーのみ使用可
@bot.command()
@commands.is_owner()
async def notify(ctx:commands.Context, *, text:str):
    embed = discord.Embed(color=0x9edfe8, title='◆◇◆◇◆お知らせ◆◇◆◇◆', description=text)
    await ctx.send('下記のお知らせを送信しますか？(y/n)', embed=embed)
    def check(m:discord.Message) -> bool:
        return (m.author == ctx.author) and (m.content in {'y', 'n'})
    msg = await bot.wait_for('message', check=check)
    if msg.content == 'y':
        ch_dic = await pg.fetchall_targetch()
        tasks = []
        for guild in bot.guilds:
            target_ch = ch_dic.setdefault(str(guild.id), 'all')
            if target_ch == 'all':
                notify_ch = guild.system_channel
            else:
                notify_ch = await bot.fetch_channel(int(target_ch))
            tasks.append(send_notify(guild.name, notify_ch, embed))
        done = await asyncio.gather(*tasks)
        await ctx.send(f'導入サーバーにお知らせを送信しました．({sum(done)}/{len(bot.guilds)})')
        logger.info(f'導入サーバーにお知らせを送信しました．({sum(done)}/{len(bot.guilds)})')
    else:
        await ctx.send('お知らせの送信を中止しました．')


@bot.command()
@commands.guild_only()
@commands.check(is_target_ch)
async def help(ctx:commands.Context, option:normalized_str=None):
    logger.info(f'「{ctx.guild.name}」の「{ctx.author.name}」がコマンドを使用しました．')
    guild_conf = await pg.fetch(ctx.guild)
    prefix = guild_conf['prefix']
    if option == 'voice':
        await ctx.send(embed=help_embed(prefix, 'voice'))
    elif option == 'setting':
        await ctx.send(embed=help_embed(prefix,'setting'))    
    else:
        await ctx.send(embed=help_embed(prefix))


@bot.command()
@commands.guild_only()
@commands.check(is_target_ch)
async def join(ctx:commands.Context):
    logger.info(f'「{ctx.guild.name}」の「{ctx.author.name}」がコマンドを使用しました．')
    if ctx.author.voice is None:
        await ctx.send('ボイスチャンネルに入室してから呼び出してください．')
    else:
        if ctx.voice_client:
            if ctx.author.voice.channel == ctx.voice_client.channel:
                await play_wav('./wav/already_joined.wav', ctx.voice_client)
        else:
            await ctx.author.voice.channel.connect()
            await play_wav('./wav/join.wav', ctx.voice_client)


@bot.command()
@commands.guild_only()
@commands.check(is_target_ch)
async def leave(ctx:commands.Context):
    logger.info(f'「{ctx.guild.name}」の「{ctx.author.name}」がコマンドを使用しました．')
    if ctx.voice_client is None:
        await ctx.send('ボイスチャンネルに入室していません．')
    else:
        await play_wav('./wav/leave.wav', ctx.voice_client)
        while ctx.voice_client.is_playing():
            await asyncio.sleep(1)
        await ctx.voice_client.disconnect()


@bot.command()
@commands.guild_only()
@commands.check(is_target_ch)
async def voice(ctx:commands.Context, option:normalized_str=None):
    logger.info(f'「{ctx.guild.name}」の「{ctx.author.name}」がコマンドを使用しました．')
    old_voice_conf = await pg.fetch(ctx.author)

    if option == 'reset':
        new_voice_conf = pg.get_default('user')
        if new_voice_conf == old_voice_conf:
            await ctx.send('すでにボイス設定はリセットされています．')
        else:
            embed = conf_embed(ctx.author, old_voice_conf, new_voice_conf)
            embed.set_author(name='ボイス設定をリセットしました．', icon_url=bot.user.avatar_url)
            text = my_normalizer(f'どうも，{ctx.author.display_name}です．')
            await asyncio.gather(
                pg.set(ctx.author, new_voice_conf),
                ctx.send(embed=embed),
                read_text(text, new_voice_conf, ctx.voice_client)
            )

    elif option == 'random':
        new_voice_conf = random_voice()
        embed = conf_embed(ctx.author, old_voice_conf, new_voice_conf)
        embed.set_author(name='ボイス設定をランダムに変更しました．', icon_url=bot.user.avatar_url)
        text = my_normalizer(f'どうも，{ctx.author.display_name}です．')
        await asyncio.gather(
            pg.set(ctx.author, new_voice_conf),
            ctx.send(embed=embed),
            read_text(text, new_voice_conf, ctx.voice_client)
        )
    
    else:
        text = my_normalizer(f'どうも，{ctx.author.display_name}です．')
        await asyncio.gather(
            ctx.send(embed=conf_embed(ctx.author, old_voice_conf, None)),
            read_text(text, old_voice_conf, ctx.voice_client)
        )


@bot.command()
@commands.guild_only()
@commands.check(is_target_ch)
async def speaker(ctx:commands.Context, arg:normalized_str=None):
    logger.info(f'「{ctx.guild.name}」の「{ctx.author.name}」がコマンドを使用しました．')
    if arg not in {'mei', 'takumi'}:
        await ctx.send(f'話者は [mei, takumi] から指定してください．\n例「{ctx.prefix}speaker mei」')
    else:
        old_voice_conf = await pg.fetch(ctx.author)
        if arg == old_voice_conf['speaker']:
            await ctx.send(f'すでに話者は「{arg}」に設定されています．')
        else:
            new_voice_conf = deepcopy(old_voice_conf)
            new_voice_conf['speaker'] = arg
            embed = conf_embed(ctx.author, old_voice_conf, new_voice_conf)
            embed.set_author(name=f'話者を「{arg}」に変更しました．', icon_url=bot.user.avatar_url)
            text = my_normalizer(f'どうも，{ctx.author.display_name}です．')
            await asyncio.gather(
                pg.set(ctx.author, new_voice_conf),
                ctx.send(embed=embed),
                read_text(text, new_voice_conf, ctx.voice_client)
            )


@bot.command()
@commands.guild_only()
@commands.check(is_target_ch)
async def emotion(ctx:commands.Context, arg:normalized_str=None):
    logger.info(f'「{ctx.guild.name}」の「{ctx.author.name}」がコマンドを使用しました．')
    if arg not in {'normal', 'happy', 'angry', 'sad'}:
        await ctx.send(f'感情は [normal, happy, angry, sad] から指定してください．\n例「{ctx.prefix}emotion happy」')
    else:
        old_voice_conf = await pg.fetch(ctx.author)
        if arg == old_voice_conf['emotion']:
            await ctx.send(f'すでに感情は「{arg}」に設定されています．')
        else:
            new_voice_conf = deepcopy(old_voice_conf)
            new_voice_conf['emotion'] = arg
            embed = conf_embed(ctx.author, old_voice_conf, new_voice_conf)
            embed.set_author(name=f'感情を「{arg}」に変更しました．', icon_url=bot.user.avatar_url)
            text = my_normalizer(f'どうも，{ctx.author.display_name}です．')
            await asyncio.gather(
                pg.set(ctx.author, new_voice_conf),
                ctx.send(embed=embed),
                read_text(text, new_voice_conf, ctx.voice_client)
            )


@bot.command()
@commands.guild_only()
@commands.check(is_target_ch)
async def effect(ctx:commands.Context, arg:normalized_str=None):
    logger.info(f'「{ctx.guild.name}」の「{ctx.author.name}」がコマンドを使用しました．')
    if arg not in {'none', 'robot', 'whisper'}:
        await ctx.send(f'エフェクトは [none, robot, whisper] から指定してください．\n例「{ctx.prefix}effect whisper」')
    else:
        old_voice_conf = await pg.fetch(ctx.author)
        if arg == old_voice_conf['effect']:
            await ctx.send(f'すでにエフェクトは「{arg}」に設定されています．')
        else:
            new_voice_conf = deepcopy(old_voice_conf)
            new_voice_conf['effect'] = arg
            embed = conf_embed(ctx.author, old_voice_conf, new_voice_conf)
            embed.set_author(name=f'エフェクトを「{arg}」に変更しました．', icon_url=bot.user.avatar_url)
            text = my_normalizer(f'どうも，{ctx.author.display_name}です．')
            await asyncio.gather(
                pg.set(ctx.author, new_voice_conf),
                ctx.send(embed=embed),
                read_text(text, new_voice_conf, ctx.voice_client)
            )


@bot.command()
@commands.guild_only()
@commands.check(is_target_ch)
async def tone(ctx:commands.Context, arg:signed_int_str=None):
    logger.info(f'「{ctx.guild.name}」の「{ctx.author.name}」がコマンドを使用しました．')
    if arg not in {'-5', '-4', '-3', '-2', '-1', '0', '+1', '+2', '+3', '+4', '+5'}:
        await ctx.send(f'トーンは [-5 ~ +5] の範囲で指定してください．\n例「{ctx.prefix}tone +2」')
    else:
        old_voice_conf = await pg.fetch(ctx.author)
        if arg == old_voice_conf['tone']:
            await ctx.send(f'すでにトーンは「{arg}」に設定されています．')
        else:
            new_voice_conf = deepcopy(old_voice_conf)
            new_voice_conf['tone'] = arg
            embed = conf_embed(ctx.author, old_voice_conf, new_voice_conf)
            embed.set_author(name=f'トーンを「{arg}」に変更しました．', icon_url=bot.user.avatar_url)
            text = my_normalizer(f'どうも，{ctx.author.display_name}です．')
            await asyncio.gather(
                pg.set(ctx.author, new_voice_conf),
                ctx.send(embed=embed),
                read_text(text, new_voice_conf, ctx.voice_client)
            )


@bot.command()
@commands.guild_only()
@commands.check(is_target_ch)
async def speed(ctx:commands.Context, arg:signed_int_str=None):
    logger.info(f'「{ctx.guild.name}」の「{ctx.author.name}」がコマンドを使用しました．')
    if arg not in {'-5', '-4', '-3', '-2', '-1', '0', '+1', '+2', '+3', '+4', '+5'}:
        await ctx.send(f'スピードは [-5 ~ +5] の範囲で指定してください．\n例「{ctx.prefix}speed -1」')
    else:
        old_voice_conf = await pg.fetch(ctx.author)
        if arg == old_voice_conf['speed']:
            await ctx.send(f'すでにスピードは「{arg}」に設定されています．')
        else:
            new_voice_conf = deepcopy(old_voice_conf)
            new_voice_conf['speed'] = arg
            embed = conf_embed(ctx.author, old_voice_conf, new_voice_conf)
            embed.set_author(name=f'スピードを「{arg}」に変更しました．', icon_url=bot.user.avatar_url)
            text = my_normalizer(f'どうも，{ctx.author.display_name}です．')
            await asyncio.gather(
                pg.set(ctx.author, new_voice_conf),
                ctx.send(embed=embed),
                read_text(text, new_voice_conf, ctx.voice_client)
            )


@bot.command()
@commands.guild_only()
@commands.check(is_target_ch)
async def setting(ctx:commands.Context, option:normalized_str=None):
    logger.info(f'「{ctx.guild.name}」の「{ctx.author.name}」がコマンドを使用しました．')
    old_guild_conf = await pg.fetch(ctx.guild)

    if option == 'reset':
        new_guild_conf = pg.get_default('guild')
        if new_guild_conf == old_guild_conf:
            await ctx.send('すでにサーバー設定はリセットされています．')
        else:
            embed = conf_embed(ctx.guild, old_guild_conf, new_guild_conf)
            embed.set_author(name='サーバー設定をリセットしました．', icon_url=bot.user.avatar_url)
            await asyncio.gather(
                pg.set(ctx.guild, new_guild_conf),
                ctx.send(embed=embed)
            )

    else:
        await ctx.send(embed=conf_embed(ctx.guild, old_guild_conf, None))


@bot.command()
@commands.guild_only()
@commands.check(is_target_ch)
async def prefix(ctx:commands.Context, arg:str=None):
    logger.info(f'「{ctx.guild.name}」の「{ctx.author.name}」がコマンドを使用しました．')
    if arg is None:
        await ctx.send(f'プレフィックスを指定してください．空白を含める場合は""で囲ってください．\n例「{ctx.prefix}prefix !?」\n　「{ctx.prefix}prefix "!s "」')
    else:
        old_guild_conf = await pg.fetch(ctx.guild)
        if arg == old_guild_conf['prefix']:
            await ctx.send(f'すでプレフィックスは「{arg}」に設定されています．')
        else:
            new_guild_conf = deepcopy(old_guild_conf)
            new_guild_conf['prefix'] = arg
            embed = conf_embed(ctx.guild, old_guild_conf, new_guild_conf)
            embed.set_author(name=f'プレフィックスを「{arg}」に変更しました．', icon_url=bot.user.avatar_url)
            await asyncio.gather(
                pg.set(ctx.guild, new_guild_conf),
                ctx.send(embed=embed)
            )


@bot.command()
@commands.guild_only()
@commands.check(is_target_ch)
async def target_ch(ctx:commands.Context, arg:str=None):
    logger.info(f'「{ctx.guild.name}」の「{ctx.author.name}」がコマンドを使用しました．')
    if arg is None:
        await ctx.send(f'操作チャンネルを指定してください．all を指定すると全てのチャンネルに反応します．\n例「{ctx.prefix}target_ch #しゃべりな用」\n　「{ctx.prefix}target_ch all」')
    else:
        old_guild_conf = await pg.fetch(ctx.guild)
        if normalized_str(arg) == 'all':
            if 'all' == old_guild_conf['target_ch']:
                await ctx.send('すでに操作チャンネルは「all」に設定されています．')
            else:
                new_guild_conf = deepcopy(old_guild_conf)
                new_guild_conf['target_ch'] = 'all'
                embed = conf_embed(ctx.guild, old_guild_conf, new_guild_conf)
                embed.set_author(name='操作チャンネルを「all」に変更しました．', icon_url=bot.user.avatar_url)
                await asyncio.gather(
                    pg.set(ctx.guild, new_guild_conf),
                    ctx.send(embed=embed)
                )
        else:
            conv = commands.TextChannelConverter()
            new_ch = await conv.convert(ctx, arg)
            if new_ch not in ctx.guild.text_channels:
                await ctx.send(f'サーバー「{ctx.guild.name}」内のチャンネルを指定してください．')
            elif str(new_ch.id) == old_guild_conf['target_ch']:
                await ctx.send(f'すでに操作チャンネルは{new_ch.mention}に設定されています．')
            else:
                new_guild_conf = deepcopy(old_guild_conf)
                new_guild_conf['target_ch'] = str(new_ch.id)
                embed = conf_embed(ctx.guild, old_guild_conf, new_guild_conf)
                embed.set_author(name=f'操作チャンネルを「#{new_ch.name}」に変更しました．', icon_url=bot.user.avatar_url)
                await asyncio.gather(
                    pg.set(ctx.guild, new_guild_conf),
                    ctx.send(embed=embed)
                )


@bot.command()
@commands.guild_only()
@commands.check(is_target_ch)
async def auto_join(ctx:commands.Context, arg:normalized_str=None):
    logger.info(f'「{ctx.guild.name}」の「{ctx.author.name}」がコマンドを使用しました．')
    if arg not in {'on', 'off'}:
        await ctx.send(f'自動入室は on/off で指定してください．\n例「{ctx.prefix}auto_join off」')
    else:
        bool_arg = (arg == 'on')
        old_guild_conf = await pg.fetch(ctx.guild)
        if bool_arg is old_guild_conf['auto_join']:
            await ctx.send(f'すでに自動入室は「{arg}」に設定されています．')
        else:
            new_guild_conf = deepcopy(old_guild_conf)
            new_guild_conf['auto_join'] = bool_arg
            embed = conf_embed(ctx.guild, old_guild_conf, new_guild_conf)
            embed.set_author(name=f'自動入室を「{arg}」に変更しました．', icon_url=bot.user.avatar_url)
            await asyncio.gather(
                pg.set(ctx.guild, new_guild_conf),
                ctx.send(embed=embed)
            )
        

@bot.command()
@commands.guild_only()
@commands.check(is_target_ch)
async def read_access(ctx:commands.Context, arg:normalized_str=None):
    logger.info(f'「{ctx.guild.name}」の「{ctx.author.name}」がコマンドを使用しました．')
    if arg not in {'on', 'off'}:
        await ctx.send(f'入退室読み上げは on/off で指定してください．\n例「{ctx.prefix}read_access off」')
    else:
        bool_arg = (arg == 'on')
        old_guild_conf = await pg.fetch(ctx.guild)
        if bool_arg is old_guild_conf['read_access']:
            await ctx.send(f'すでに入退室読み上げは「{arg}」に設定されています．')
        else:
            new_guild_conf = deepcopy(old_guild_conf)
            new_guild_conf['read_access'] = bool_arg
            embed = conf_embed(ctx.guild, old_guild_conf, new_guild_conf)
            embed.set_author(name=f'入退室読み上げを「{arg}」に変更しました．', icon_url=bot.user.avatar_url)
            await asyncio.gather(
                pg.set(ctx.guild, new_guild_conf),
                ctx.send(embed=embed)
            )


@bot.command()
@commands.guild_only()
@commands.check(is_target_ch)
async def read_author(ctx:commands.Context, arg:normalized_str=None):
    logger.info(f'「{ctx.guild.name}」の「{ctx.author.name}」がコマンドを使用しました．')
    if arg not in {'on', 'off'}:
        await ctx.send(f'送信者名読み上げは on/off で指定してください．\n例「{ctx.prefix}read_author on」')
    else:
        bool_arg = (arg == 'on')
        old_guild_conf = await pg.fetch(ctx.guild)
        if bool_arg is old_guild_conf['read_author']:
            await ctx.send(f'すでに送信者名読み上げは「{arg}」に設定されています．')
        else:
            new_guild_conf = deepcopy(old_guild_conf)
            new_guild_conf['read_author'] = bool_arg
            embed = conf_embed(ctx.guild, old_guild_conf, new_guild_conf)
            embed.set_author(name=f'送信者名読み上げを「{arg}」に変更しました．', icon_url=bot.user.avatar_url)
            await asyncio.gather(
                pg.set(ctx.guild, new_guild_conf),
                ctx.send(embed=embed)
            )


@bot.command()
@commands.guild_only()
@commands.check(is_target_ch)
async def read_outsider(ctx:commands.Context, arg:normalized_str=None):
    logger.info(f'「{ctx.guild.name}」の「{ctx.author.name}」がコマンドを使用しました．')
    if arg not in {'on', 'off'}:
        await ctx.send(f'非参加者読み上げは on/off で指定してください．\n例「{ctx.prefix}read_outsider on」')
    else:
        bool_arg = (arg == 'on')
        old_guild_conf = await pg.fetch(ctx.guild)
        if bool_arg is old_guild_conf['read_outsider']:
            await ctx.send(f'すでに非参加者読み上げは「{arg}」に設定されています．')
        else:
            new_guild_conf = deepcopy(old_guild_conf)
            new_guild_conf['read_outsider'] = bool_arg
            embed = conf_embed(ctx.guild, old_guild_conf, new_guild_conf)
            embed.set_author(name=f'非参加者読み上げを「{arg}」に変更しました．', icon_url=bot.user.avatar_url)
            await asyncio.gather(
                pg.set(ctx.guild, new_guild_conf),
                ctx.send(embed=embed)
            )


@bot.event
async def on_message(message:discord.Message):
    
    #「help」だけはprefixによらず使用可能に
    if (text:=message.content).startswith(pg.get_default('guild')['prefix'] + 'help'):
        if message.guild is None:
            await message.channel.send('DMでの操作には対応していません．')
        else:
            ctx = await bot.get_context(message)
            if await is_target_ch(ctx):
                arg = None
                if len(args:=text.split(' ')) != 1:
                    arg = normalized_str(args[1])
                await ctx.invoke(help, option=arg)
        return
    
    #全サーバー共通のチェック
    if message.guild is None:
        pass
    elif message.guild.voice_client is None:
        pass
    elif message.author.bot:
        pass

    else:
        #サーバーごとのチェック
        guild_conf = await pg.fetch(message.guild)
        if (guild_conf['target_ch'] != 'all') and (guild_conf['target_ch'] != str(message.channel.id)):
            pass
        elif (not guild_conf['read_outsider']) and ((message.author.voice is None) or (message.author.voice.channel is not message.guild.voice_client.channel)):
            pass
        elif message.content.startswith(guild_conf['prefix']):
            pass
        #target_ch以外では反応しないようにサーバー毎でチェック
        elif len(message.content) > 100:
            await message.channel.send('文字数が多すぎます．')

        else:
            task = asyncio.create_task(pg.fetch(message.author))
            text = await modify_text(message, guild_conf, bot)
            text = my_normalizer(text)
            voice_conf = await task
            await read_text(text, voice_conf, message.guild.voice_client)
        
    await bot.process_commands(message)


@bot.event
async def on_voice_state_update(member:discord.Member, before:discord.VoiceClient, after:discord.VoiceClient):
    guild_conf = await pg.fetch(member.guild)

    #誰かが入室したとき
    if before.channel is None:
        if member.id == bot.user.id:
            logger.info(f'サーバー「{member.guild.name}」のVCに入室しました．')
            presence = f'{default_prefix}help | {len(bot.voice_clients)}/{len(bot.guilds)}サーバー'
            await bot.change_presence(activity=discord.Game(name=presence))
        else:
            if member.guild.voice_client is None:
                if member.voice.self_mute and guild_conf['auto_join']:
                    await asyncio.sleep(1)
                    await after.channel.connect()
                    await play_wav('./wav/auto_join.wav', member.guild.voice_client)
            else:
                if member.guild.voice_client.channel is after.channel:
                    if guild_conf['read_access']:
                        text = my_normalizer(f'{member.name}さんが入室しました．')
                        await read_text(text, pg.get_default('user'), member.guild.voice_client)
    
    #誰かが退出したとき
    elif after.channel is None:
        if member.id == bot.user.id:
            logger.info(f'サーバー「{member.guild.name}」のVCから退室しました．')
            presence = f'{default_prefix}help | {len(bot.voice_clients)}/{len(bot.guilds)}サーバー'
            await bot.change_presence(activity=discord.Game(name=presence))
        else:
            if member.guild.voice_client:
                if member.guild.voice_client.channel is before.channel:
                    if len(member.guild.voice_client.channel.members) == 1:
                        await asyncio.sleep(1)
                        await member.guild.voice_client.disconnect()
                    elif guild_conf['read_access']:
                        text = my_normalizer(f'{member.name}さんが退室しました．')
                        await read_text(text, pg.get_default('user'), member.guild.voice_client)

    #誰かが移動したとき
    elif before.channel is not after.channel:
        if member.guild.voice_client is None:
            if member.voice.self_mute and guild_conf['auto_join']:
                await asyncio.sleep(1)
                await after.channel.connect()
                await play_wav('./wav/auto_join.wav', member.guild.voice_client)
        else:
            if member.guild.voice_client.channel is before.channel:
                if len(member.guild.voice_client.channel.members) == 1:
                    await asyncio.sleep(1)
                    await member.guild.voice_client.disconnect()
    
    #ミュートに変更したとき
    elif after.self_mute > before.self_mute:
        if (member.guild.voice_client is None) and guild_conf['auto_join']:
            await member.voice.channel.connect()
            await play_wav('./wav/auto_join.wav', member.guild.voice_client)


@bot.event
async def on_command_error(ctx:commands.Context, error:commands.CommandError):
    if isinstance(error, (commands.CommandNotFound, commands.ChannelNotFound, commands.BadArgument, commands.NoPrivateMessage, commands.CheckFailure, AttributeError)):
        pass
    else:
        logger.error(f'{error.__class__.__name__}: {error}')
    
    if (ctx.guild is None) and (ctx.author.id != bot.owner_id):
        await ctx.send('DMでの操作には対応していません．')
    #下記ではDMで存在しないコマンドがたたかれたときに「コマンドが存在しません．」が出力されてしまう
    #elif isinstance(error, commands.NoPrivateMessage):
    #    await ctx.send('DMでの操作には対応していません．')
    elif isinstance(error, commands.CommandNotFound):
        await ctx.send(f'コマンドが存在しません．')
    elif isinstance(error, commands.ChannelNotFound):
        await ctx.send('チャンネルが特定できませんでした．')
    elif isinstance(error, commands.BadArgument):
        await ctx.send('数値が認識できませんでした．[-5 ~ +5] の範囲で指定してください．')
    elif isinstance(error, (commands.CheckFailure, AttributeError)):
        pass
    else:
        await ctx.send('エラーが発生しました．しばらく時間を空けてからお試しください．')

#ここまでbotの挙動
########################################################################################################

logger.debug('botを起動しています．')
bot.run(TOKEN)
