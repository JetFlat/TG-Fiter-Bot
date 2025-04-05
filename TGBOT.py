import asyncio
import logging
import sys
import os
import asyncpg
from os import getenv
from aiogram import Bot, Dispatcher, Router, types, F
from aiogram.types import Message
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
bot = Bot(token = TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)


HELP_COMMANDS = """
    /start - initialize bot,
    /help - bot's commands,
    /languge - choose the language,
    /show_cat - show my categories
"""

#Connection to database
logging.basicConfig(level=logging.INFO)
async def connect_to_db():
    try:
        conn = await asyncpg.connect(
            user = 'postgres',
            password = 'postgres',
            database = 'postgres',
            host = '127.0.0.1',
            port = '5432'
        )
        logging.info("Creating 'users' table if not exists")
        await conn.execute ("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY NOT NULL,
                user_id BIGINT UNIQUE NOT NULL,
                username TEXT,
                first_name TEXT NOT NULL
            )
        """)
        logging.info("Creating 'notes' table if not exists")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS notes (
                id SERIAL PRIMARY KEY,
                user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
                content_type TEXT,
                category TEXT
            )
        """)
        return conn
    except Exception as e:
        logging.error(f'Error connected to database: {e}')
        return None



#Command start - 2 buttons added, will be added some more after
@router.message(Command('start'))
async def start(message: types.Message):
    conn = await connect_to_db()
    user_id = message.from_user.id
    user_name = message.from_user.username
    first_name = message.from_user.first_name

    await conn.execute('''
        INSERT INTO users (user_id, username, first_name) 
        VALUES ($1, $2, $3)
        ON CONFLICT (user_id) DO NOTHING''', user_id, user_name, first_name)

    markup = ReplyKeyboardMarkup(
        keyboard = [[KeyboardButton(text='Help'), KeyboardButton(text='Add a new category'),
                     KeyboardButton(text='Language'),KeyboardButton(text='Show categories')]], resize_keyboard=True,
    )
    await message.answer('<b>Hello there</b>', parse_mode='html',reply_markup=markup)

@router.message(F.text.in_({'Help', 'Add a new category'}))
async def handle_reply_buttons(message: types.Message):
    if message.text == "Help":
        await message.answer(HELP_COMMANDS)
    elif message.text == "Add a new category":
        await message.answer("Name the new category!")




async def main():
    print("Bot has been started!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())