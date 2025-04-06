import asyncio
import logging
import sys
import os
import asyncpg
from os import getenv
from aiogram import Bot, Dispatcher, Router, types, F
from aiogram.types import Message
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command, StateFilter
from dotenv import load_dotenv
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup


load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
bot = Bot(token = TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)


class CategoryForm(StatesGroup):
    waiting_for_category_name = State()


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
        await conn.execute ("""
            CREATE TABLE IF NOT EXISTS notes (
                id SERIAL PRIMARY KEY,
                user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
                content_type TEXT,
                category_id INT REFERENCES categories(id) ON DELETE CASCADE,
                note_content TEXT
            )
        """)
        logging.info("Creating 'categories' table if not exists")
        await conn.execute ("""
            CREATE TABLE IF NOT EXISTS categories (
                id SERIAL PRIMARY KEY,
                user_id BIGINT REFERENCES users (user_id) ON DELETE CASCADE,
                category_name TEXT NOT NULL,
                UNIQUE (user_id, category_name)
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

@router.message(F.text.in_({'Help'}))
async def handle_reply_buttons(message: types.Message):
    await message.answer(HELP_COMMANDS)

#Func to get the name of the category to be added
@router.message(F.text.in_({'Add a new category'}))
async def add_category_prompt(message: types.Message, state:FSMContext):
    #Send a request to user to provide category name
    await state.set_state (CategoryForm.waiting_for_category_name)
    await message.answer("Please enter the name of the new category!")

#Handler for the category name. FSMState added to avoid situation of handler to be called somewhere in other part of program
@router.message(StateFilter(CategoryForm.waiting_for_category_name))
async def handle_category_name(message: types.Message, state:FSMContext):
    user_id = message.from_user.id
    category_name = message.text.strip()

    if not category_name:
        await message.answer('The name of category can not be empty.')
        return
    conn = await connect_to_db()
    try:
        await conn.execute(""" 
            INSERT INTO categories (user_id, category_name)
            VALUES ($1, $2)
            ON CONFLICT (user_id, category_name) DO NOTHING
        """, user_id, category_name)
        await message.answer(f'A category {category_name} was added!')
    except Exception as e:
        logging.error(f"Error creating category: {e}")
        await message.answer("There was an error while creating the category.")

    await state.clear()

def build_inline_keyboard(buttons: list[InlineKeyboardButton], row_width: int = 2) -> InlineKeyboardMarkup:
    keyboard = [buttons[i:i + row_width] for i in range(0, len(buttons), row_width)]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

#Handler which shows all categories which user has already
@router.message(F.text.in_({'Show categories'}))
async def show_categories(message:types.Message):
    user_id = message.from_user.id
    conn = await connect_to_db()

    categories = await conn.fetch ("""
        SELECT id, category_name FROM categories
        WHERE user_id = $1""", user_id
    )
    if not categories:
        await message.answer('You have no categories yet')

    buttons = [
        InlineKeyboardButton(text=cat['category_name'], callback_data=f"note_cat_{cat['id']}")
        for cat in categories
    ]

    keyboard = build_inline_keyboard(buttons, row_width=3)

    await message.answer(f'Your caterogies:', reply_markup=keyboard)
    await conn.close()

async def main():
    print("Bot has been started!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())


#Category handler realized via FSM State machine
#-> Next step is to make all catergories in the shown list clickable with link to this cat's items
#-> Add the note to the bot and filter by category