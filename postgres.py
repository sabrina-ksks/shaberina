import asyncpg
from collections import OrderedDict
from copy import deepcopy
from typing import Literal, Union
import discord
from utils import random_voice

from logging import getLogger, StreamHandler, Formatter, DEBUG, INFO


logger = getLogger(__name__)
logger.setLevel(DEBUG)
logger.propagate = False
hdlr = StreamHandler()
hdlr.setLevel(DEBUG)
fmt = Formatter(fmt='[{asctime}][{name}][{funcName}][{levelname}] {message}', datefmt='%Y-%m-%d %H:%M:%S' ,style='{')
hdlr.setFormatter(fmt)
logger.addHandler(hdlr)

DEFAULT = {
    'user': {
        'speaker': 'mei',
        'emotion': 'normal',
        'effect': 'none',
        'tone': '0',
        'speed': '0'
    },
    'guild': {
        'prefix': ';',
        'target_ch': 'all',
        'auto_join': True,
        'read_access': True,
        'read_author': False,
        'read_outsider': False,
    }
}

CACHE_SIZE = {
    'user': 100,
    'guild': 50
}


class LRUCache:
    def __init__(self, name:str, size:int) -> None:
        self.body = OrderedDict()
        self.name = name
        self.size = size
        self.is_full = False
    
    def get(self, key:str) -> dict:
        if key not in self.body:
            return None
        else:
            self.body.move_to_end(key)
            return deepcopy(self.body[key])

    def put(self, key:str, value:dict) -> None:
        #空きがあるとき
        if not self.is_full:
            if key in self.body:
                del self.body[key]
                self.body[key] = deepcopy(value)
            else:
                self.body[key] = deepcopy(value)
                logger.debug(f'キャッシュに{self.name}データを保存しました．({len(self.body)}/{self.size})')
            #キャッシュがいっぱいになったとき
            if len(self.body) == self.size:
                self.is_full = True
                logger.warning(f'{self.name}データのキャッシュ上限に達しました．容量を確認してください．({len(self.body)}/{self.size})')
        #キャッシュがいっぱいのとき
        else:
            if key in self.body:
                del self.body[key]
                self.body[key] = deepcopy(value)
            else:
                self.body.popitem(last=False)
                self.body[key] = deepcopy(value)



def vind_str(n:int) -> str:
        return ', '.join([f'${i}' for i in range(1, n+1)])


class Postgres:
    def __init__(self, URL:str) -> None:
        self.URL = URL
        self.cache = {
            'user': LRUCache('ユーザー', CACHE_SIZE['user']),
            'guild': LRUCache('サーバー', CACHE_SIZE['guild'])
        }
        self.default = deepcopy(DEFAULT)
        self.params = {
            'user': list(self.default['user'].keys()),
            'guild': list(self.default['guild'].keys())
        }
        self.n_param = {
            'user': len(self.params['user']),
            'guild': len(self.params['guild'])
        }
    

    def get_default(self, mode:Literal['user', 'guild']) -> dict:
        return deepcopy(self.default[mode])


    async def connect(self) -> None:
        self.pool = await asyncpg.create_pool(dsn=self.URL, min_size=2, max_size=8)
        logger.info('Postgresとの接続に成功しました．')


    async def fetch(self, obj:Union[discord.Member, discord.Guild]) -> dict:
        id = str(obj.id)
        if isinstance(obj,discord.Member):
            mode = 'user'
        elif isinstance(obj, discord.Guild):
            mode = 'guild'
        
        if (conf := self.cache[mode].get(id)) is not None:
            return conf
        else:
            async with self.pool.acquire() as con:
                query = f'SELECT {", ".join(self.params[mode])} FROM {mode}s WHERE id = $1;'
                if (resp := await con.fetchrow(query, id)) is not None:
                    conf = dict(resp)
                else:
                    conf = await self.create_record(obj)
            self.cache[mode].put(id, conf)
            return conf
    

    async def set(self, obj:Union[discord.Member, discord.Guild], conf:dict) -> None:
        id = str(obj.id)
        name = obj.name
        if isinstance(obj, discord.Member):
            mode = 'user'
            display_mode = 'ユーザー'
        elif isinstance(obj, discord.Guild):
            mode = 'guild'
            display_mode = 'サーバー'
        
        async with self.pool.acquire() as con:
            query = f'UPDATE {mode}s SET ({", ".join(self.params[mode])}) = ({vind_str(self.n_param[mode])}) WHERE id = ${self.n_param[mode] + 1};'
            await con.execute(query, *conf.values(), id)
        self.cache[mode].put(id, conf)
        logger.info(f'{display_mode}「{name}」のデータを更新しました．')


    async def create_record(self, obj:Union[discord.Member, discord.Guild]) -> dict:
        id = str(obj.id)
        name = obj.name
        if isinstance(obj, discord.Member):
            #ユーザーはランダム初期化
            mode = 'user'
            display_mode = 'ユーザー'
            conf = random_voice()
        elif isinstance(obj, discord.Guild):
            #サーバーはデフォルト初期化
            mode = 'guild'
            display_mode = 'サーバー'
            conf = self.get_default('guild')
        
        async with self.pool.acquire() as con:
            query = f'INSERT INTO {mode}s VALUES ({vind_str(self.n_param[mode] + 2)})'
            await con.execute(query, id, name, *conf.values())
        logger.info(f'{display_mode}「{name}」のデータを新たに登録しました．')
        return conf
    

    async def fetchall_targetch(self) -> dict:
        async with self.pool.acquire() as con:
            query = f'SELECT id, target_ch FROM guilds;'
            resp = await con.fetch(query)
        ch_dic = {}
        for row in resp:
            ch_dic[row['id']] = row['target_ch']
        return ch_dic


    async def disconnect(self) -> None:
        await self.pool.close()
        logger.info('Postgresからの切断に成功しました．')
