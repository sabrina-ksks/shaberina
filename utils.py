from copy import deepcopy
import discord
from discord.ext import commands
import re
import random
import demoji
import unicodedata
import jaconv
from typing import Literal, Union


def random_voice() -> dict:
    voice_conf = {}
    voice_conf['speaker'] = random.choice(['mei', 'takumi'])
    voice_conf['emotion'] = random.choice(['normal', 'happy', 'angry', 'sad'])
    voice_conf['effect'] = random.choice(['none', 'none', 'robot', 'whisper'])
    voice_conf['tone'] = random.choice(['-5', '-4', '-3', '-2', '-1', '0', '+1', '+2', '+3', '+4', '+5'])
    voice_conf['speed'] = '0'
    return voice_conf


def normalized_str(s:str) -> str:
    return unicodedata.normalize('NFKC', s).lower()


def signed_int_str(s:str) -> str:
    try:
        s = int(normalized_str(s))
    except Exception:
        raise commands.BadArgument
    return str(s) if s <= 0 else '+' + str(s)


def my_normalizer(text:str) -> str:
    text = unicodedata.normalize('NFKC', text)
    text = text.upper()
    text = jaconv.normalize(text, 'NFKC')
    text = jaconv.h2z(text, digit=True, ascii=True, kana=True)
    text = text.replace('\u00A5', '\uFFE5') # yen symbol
    return text


#正規表現を先にコンパイルしておく
user_mention_pattern = re.compile(r'<@!?(\d+)>')
role_mention_pattern = re.compile(r'<@&(\d+)>')
channel_mention_pattern = re.compile(r'<#(\d+)>')
special_pattern = re.compile(r'<.*>')
url_pattern = re.compile(r'https?://[\w/:%#\$&\?\(\)~\.=\+\-]+')
www_pattern = re.compile(r'(w+|W+|ｗ+|Ｗ+|笑+|\(笑\)|（笑）)$')

async def modify_text(message:discord.Message, guild_conf:dict, bot:commands.Bot) -> str:
    text = message.content
    text = text.replace('\n', '．')
    #メンションを置き換え
    match = user_mention_pattern.findall(text)
    for user_id in match:
        user = await bot.fetch_user(int(user_id))
        text = re.sub(f'<@!?{user_id}>', user.display_name, text)
    match = role_mention_pattern.findall(text)
    for role_id in match:
        role = message.guild.get_role(int(role_id))
        text = re.sub(f'<@&{role_id}>', role.name, text)
    match = channel_mention_pattern.findall(text)
    for channel_id in match:
        channel = await bot.fetch_channel(int(channel_id))
        text = re.sub(f'<#{channel_id}>', channel.name, text)
    #特殊パターンと絵文字を削除
    text = special_pattern.sub('', text)
    text = demoji.replace(text, '')
    #特定の文字列を置換
    text = url_pattern.sub('，URL，', text)
    text = www_pattern.sub('，藁．', text)
    #送信者名読み上げ
    if guild_conf['read_author'] and text != '':
        text = f'{message.author.display_name}です，{text}'
    return text


def preprocess_for_embed(old:dict, new:Union[dict, None]) -> dict:
    _old = deepcopy(old)
    _new = deepcopy(new)
    if new is None:
        for key in _old.keys():
            #表示用に書き換え
            if key == 'prefix':
                _old['prefix'] = f"「{_old['prefix']}」"
            elif key == 'target_ch':
                _old['target_ch'] = f"<#{_old['target_ch']}>" if _old['target_ch'] != 'all' else 'all'
            elif isinstance(_old[key], bool):
                _old[key] = 'on' if _old[key] else 'off'
        return _old
    else:
        product = {}
        for key in old.keys():
            #表示用に書き換え
            if key == 'prefix':
                _old['prefix'] = f"「{_old['prefix']}」"
                _new['prefix'] = f"「{_new['prefix']}」"
            elif key == 'target_ch':
                _old['target_ch'] = f"<#{_old['target_ch']}>" if _old['target_ch'] != 'all' else 'all'
                _new['target_ch'] = f"<#{_new['target_ch']}>" if _new['target_ch'] != 'all' else 'all'
            elif isinstance(old[key], bool):
                _old[key] = 'on' if _old[key] else 'off'
                _new[key] = 'on' if _new[key] else 'off'
            #異なれば矢印でつなぐ
            product[key] = f'{_old[key]}　⇒　{_new[key]}' if _old[key] != _new[key] else _new[key]
        return product


def conf_embed(obj:Union[discord.Member, discord.Guild], old_conf:dict, new_conf:Union[dict, None]) -> discord.Embed:
    preprocessed = preprocess_for_embed(old_conf, new_conf)
    if isinstance(obj, discord.Member):
        embed = discord.Embed(
            color=0x9edfe8,
            title=f'◆◇◆ボイス設定◆◇◆',
            description=
                f'**話者　　　**：{preprocessed["speaker"]}\n' \
                f'**感情　　　**：{preprocessed["emotion"]}\n' \
                f'**エフェクト**：{preprocessed["effect"]}\n' \
                f'**トーン　　**：{preprocessed["tone"]}\n' \
                f'**スピード　**：{preprocessed["speed"]}'
        )
        embed.set_thumbnail(url=obj.avatar_url)
    elif isinstance(obj, discord.Guild):
        embed = discord.Embed(
            color=0x9edfe8,
            title=f'◆◇◆サーバー設定◆◇◆',
            description=
                f'**プレフィックス　**：{preprocessed["prefix"]}\n' \
                f'**操作チャンネル　**：{preprocessed["target_ch"]}\n' \
                f'**自動入室　　　　**：{preprocessed["auto_join"]}\n' \
                f'**入退室読み上げ　**：{preprocessed["read_access"]}\n' \
                f'**送信者名読み上げ**：{preprocessed["read_author"]}\n' \
                f'**非参加者読み上げ**：{preprocessed["read_outsider"]}'
        )
        embed.set_thumbnail(url=obj.icon_url)
    return embed


def help_embed(prefix:str, option:Literal['voice', 'setting']=None) -> discord.Embed:
    if option is None:
        embed = discord.Embed(
            color=0x9edfe8,
            title='◆◇◆ヘルプ～基本編～◆◇◆',
            description=
                '読み上げbot「しゃべりな」です．ユーザーごとのボイス設定，自動入室などのサーバー設定に対応しています．\n\n' \
                '__基本操作__\n' \
                f'{prefix}join：ボイスチャンネルに入室する．\n' \
                f'{prefix}leave：ボイスチャンネルから退室する．\n' \
                '__ボイス設定__\n' \
                f'{prefix}voice：現在のボイス設定を表示する．\n' \
                f'{prefix}voice reset：ボイス設定をリセットする．\n' \
                f'{prefix}voice random：ボイス設定をランダムに変更する．\n' \
                '__サーバー設定__\n' \
                f'{prefix}setting：現在のサーバー設定を表示する．\n' \
                f'{prefix}setting reset：サーバー設定をリセットする．\n' \
                '__詳しいヘルプ__\n' \
                f'{prefix}help voice：ボイス設定の詳細を確認する．\n' \
                f'{prefix}help setting：サーバー設定の詳細を確認する．'
        )
    elif option == 'voice':
        embed = discord.Embed(
            color=0x9edfe8,
            title='◆◇◆ヘルプ～ボイス設定編～◆◇◆',
            description=
                '__コマンド一覧__\n' \
                f'{prefix}voice：現在のボイス設定を表示する．\n' \
                f'{prefix}voice reset：ボイス設定をリセットする．\n' \
                f'{prefix}voice random：ボイス設定をランダムに変更する．\n' \
                f'{prefix}speaker ＿：話者を＿に変更する．\n' \
                f'{prefix}emotion ＿：感情を＿に変更する．\n' \
                f'{prefix}effect ＿：エフェクトを＿に変更する．\n' \
                f'{prefix}tone ＿：トーンを＿に変更する．\n' \
                f'{prefix}speed ＿：スピードを＿に変更する．\n\n' \
                '__パラメータの範囲__\n' \
                '話者　　　：[mei, takumi]\n' \
                '感情　　　：[normal, happy, angry, sad]\n' \
                'エフェクト：[none, robot, whisper]\n' \
                'トーン　　：[-5 ~ +5]\n' \
                'スピード　：[-5 ~ +5]'              
        )
    elif option == 'setting':
        embed = discord.Embed(
            color=0x9edfe8,
            title='◆◇◆ヘルプ～サーバー設定編～◆◇◆',
            description=
                '__コマンド一覧__\n' \
                f'{prefix}setting：現在のサーバー設定を表示する．\n' \
                f'{prefix}setting reset：サーバー設定をリセットする．\n' \
                f'{prefix}prefix ＿：プレフィックスを＿に変更する．\n' \
                f'{prefix}target_ch ＿/all：操作チャンネルを＿/allに変更する．\n' \
                f'{prefix}auto_join on/off：自動入室を変更する．\n' \
                f'{prefix}read_access on/off：入退室読み上げを変更する．\n' \
                f'{prefix}read_author on/off：送信者名読み上げを変更する．\n' \
                f'{prefix}read_outsider on/off：非参加者読み上げを変更する．\n\n' \
        )
    return embed


def invited_embed(default_prefix:str) -> discord.Embed:
    embed = discord.Embed(
        color=0x9edfe8,
        title='◆◇◆◇◆はじめに◆◇◆◇◆',
        description=
            '読み上げbot「しゃべりな」を導入いただきありがとうございます．自動入退室に対応しているため，コマンドを覚えなくてもそのままお使いいただけます．\n\n' \
            '__　特徴　__\n' \
            '☑ミュートに反応して自動入室\n' \
            '☑ユーザーごとの多様なボイス設定\n' \
            '☑便利なサーバー設定\n\n' \
            'より快適にお使いいただくために，以下のコマンドで操作チャンネルを登録していただくことを推奨します．\n' \
            f'例「{default_prefix}target_ch #しゃべりな用」\n\n' \
            f'その他，詳しい操作方法は「{default_prefix}help」をご確認ください．'
    )
    return embed
