import asyncio
import logging
import sys
import os
from pyexpat.errors import messages

import asyncpg
from os import getenv
from aiogram import Bot, Dispatcher, Router, types, F
from aiogram.types import Message, CallbackQuery
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command, StateFilter
from dotenv import load_dotenv
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
bot = Bot(token=TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)

#Class to determine State (status) for functions with call back to be called ONLY when needed (e.g. when spec. button is pressed)
class CategoryForm(StatesGroup):
    waiting_for_category_name = State()
    waiting_for_note_text = State()
    waiting_for_search = State()


HELP_COMMANDS = """
    /start - initialize bot,
    /help - bot's commands,
    /language - choose the language,
    /show_cat - show my categories
"""

# Connection to database
logging.basicConfig(level=logging.INFO)


async def connect_to_db():
    try:
        conn = await asyncpg.connect(
            user='postgres',
            password='postgres',
            database='postgres',
            host='127.0.0.1',
            port='5432'
        )
        logging.info("Creating 'users' table if not exists")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY NOT NULL,
                user_id BIGINT UNIQUE NOT NULL,
                username TEXT,
                first_name TEXT NOT NULL
            )
        """)
        logging.info("Creating 'categories' table if not exists")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS categories (
                id SERIAL PRIMARY KEY,
                user_id BIGINT REFERENCES users (user_id) ON DELETE CASCADE,
                category_name TEXT NOT NULL,
                UNIQUE (user_id, category_name)
            )
        """)
        logging.info("Creating 'notes' table if not exists")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS notes (
                id SERIAL PRIMARY KEY,
                user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
                content_type TEXT,
                category_id INT REFERENCES categories(id) ON DELETE CASCADE,
                note_content TEXT,
                caption TEXT,
                file_id TEXT,
                forward_chat_id BIGINT,
                forward_message_id INT
            )
        """)
        return conn
    except Exception as e:
        logging.error(f'Error connected to database: {e}')
        return None


# Command start - NEED TO ADD CALLBACK TO BUTTONS
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
        keyboard=[
            [KeyboardButton(text='Help'), KeyboardButton(text='Search')],
            [KeyboardButton(text='Add a new category'),KeyboardButton(text='Language')],
            [KeyboardButton(text='Show categories'), KeyboardButton(text='Show my notes')]
        ], resize_keyboard=True,
    )
    await message.answer('<b>Hello there</b>', parse_mode='html', reply_markup=markup)


@router.message(F.text.in_({'Help'}))
async def handle_reply_buttons(message: types.Message):
    await message.answer(HELP_COMMANDS)


# Func to get the name of the category to be added
@router.message(F.text.in_({'Add a new category'}))
async def add_category_prompt(message: types.Message, state: FSMContext):
    # Send a request to user to provide category name
    await state.set_state(CategoryForm.waiting_for_category_name)
    await message.answer("Please enter the name of the new category!")


# Handler for the category name. FSMState added to avoid situation of handler to be called somewhere in other part of program
@router.message(StateFilter(CategoryForm.waiting_for_category_name))
async def handle_category_name(message: types.Message, state: FSMContext):
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

#Function for inline keyboard
def build_inline_keyboard(buttons: list[InlineKeyboardButton], row_width: int = 2) -> InlineKeyboardMarkup:
    keyboard = [buttons[i:i + row_width] for i in range(0, len(buttons), row_width)]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

#Handler for direct and forwarded msg
@router.message(
    StateFilter(None),  # Ensure we're not in any state
    F.forward_from.as_("has_forward") |
    F.forward_from_chat.as_("has_forward_chat") |
    F.forward_sender_name.as_("has_forward_name") |
    F.photo.as_("has_photo") |
    F.video.as_("has_video") |
    F.document.as_("has_doc") |
    F.audio.as_("has_audio") |
    F.voice.as_("has_voice") |
    F.sticker.as_("has_sticker") |
    (F.text & ~F.text.in_({"Show categories", "Show my notes", "Help", "Add a note", "Add a new category", "Language", "Search"}))
)
async def handle_forwarded_and_direct(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    caption = message.caption or ""
    content_type = None
    note_content = None
    file_id = None
    forward_chat_id = None
    forward_message_id = None

    if message.photo:
        content_type = 'photo'
        file_id = message.photo[-1].file_id
        note_content = caption
    elif message.video:
        content_type = 'video'
        file_id = message.video.file_id
        note_content = caption
    elif message.document:
        content_type = 'document'
        file_id = message.document.file_id
        note_content = caption
    elif message.audio:
        content_type = 'audio'
        file_id = message.audio.file_id
        note_content = caption
    elif message.voice:
        content_type = 'voice'
        file_id = message.voice.file_id
        note_content = caption
    elif message.sticker:
        content_type = 'sticker'
        file_id = message.sticker.file_id
        note_content = "Sticker"
    elif message.text:
        content_type = 'text'
        note_content = message.text
    else:
        await message.answer("Этот тип сообщения пока не поддерживается.")
        return

    if message.forward_from_chat or message.forward_from or message.forward_sender_name:
        forward_chat_id = getattr(message.forward_from_chat, 'id', None)
        forward_message_id = message.forward_from_message_id

        if not note_content:
            note_content = "forwarded message"
        content_type = f"forwarded_{content_type}" if content_type else "forwarded"


    await state.update_data(
        note_content=note_content,
        content_type=content_type,
        file_id=file_id,
        caption=caption,
        forward_chat_id=forward_chat_id,
        forward_message_id=forward_message_id
    )


    conn = await connect_to_db()
    categories = await conn.fetch('SELECT id, category_name FROM categories WHERE user_id=$1', user_id)
    await conn.close()

    if not categories:
        await message.answer('У вас пока нет ни одной категории.')
        return


    buttons = [
        InlineKeyboardButton(text=cat['category_name'], callback_data=f'save_note_cat_{cat["id"]}')
        for cat in categories
    ]
    keyboard = build_inline_keyboard(buttons, row_width=2)

    await message.answer('Выберите категорию для этой заметки:', reply_markup=keyboard)


@router.callback_query(F.data.startswith('save_note_cat_'))
async def save_note_callback(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    category_id = int(callback.data.split("_")[-1])
    state_data = await state.get_data()

    content = state_data.get('note_content')
    content_type = state_data.get('content_type')
    file_id = state_data.get('file_id')
    caption = state_data.get('caption')
    forward_chat_id = state_data.get('forward_chat_id')
    forward_message_id = state_data.get('forward_message_id')

    if not content and not file_id and not forward_message_id:
        await callback.message.edit_text('Your note is empty')
        return

    conn = await connect_to_db()

    await conn.execute("""
        INSERT INTO notes (user_id, category_id, content_type, note_content, caption, file_id, forward_chat_id, forward_message_id)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        """, user_id, category_id, content_type, content, caption, file_id, forward_chat_id, forward_message_id
                       )

    await conn.close()
    await callback.message.edit_text('Note saved successfully!')
    await state.clear()


#Handler to show all categories for user
@router.message(F.text.in_({'Show categories'}))
async def show_categories(message: Message):
    user_id = message.from_user.id
    conn = await connect_to_db()

    categories = await conn.fetch("""
        SELECT id, category_name FROM categories
        WHERE user_id = $1
        """, user_id
                                  )

    if not categories:
        await message.answer('You have no categories yet')
        await conn.close()
        return

    buttons = [
        InlineKeyboardButton(text=cat['category_name'], callback_data=f"show_cat_notes_{cat['id']}")
        for cat in categories
    ]

    keyboard = build_inline_keyboard(buttons, row_width=3)

    await message.answer(f'Your categories:', reply_markup=keyboard)
    await conn.close()


# Handler to show note byt the category
@router.callback_query(F.data.startswith('show_cat_notes_'))
async def show_category_notes(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    category_id = int(callback.data.split("_")[-1])

    conn = await connect_to_db()


    category = await conn.fetchrow("""
        SELECT category_name FROM categories WHERE id = $1
        """, category_id
                                   )

    if not category:
        await callback.message.edit_text('Category not found.')
        await conn.close()
        return


    notes = await conn.fetch("""
        SELECT id, note_content, content_type, file_id, caption, forward_chat_id, forward_message_id
        FROM notes WHERE user_id = $1 AND category_id = $2
        ORDER BY id
        """, user_id, category_id
                             )

    await conn.close()

    if not notes:
        await callback.message.edit_text(f'No notes in category "{category["category_name"]}".')
        return

    await state.update_data(notes=notes, current_index=0, category_name=category["category_name"])
    await display_note(callback.message.chat.id, notes[0], 0, len(notes), state)



async def get_note_by_id(note_id: int):
    conn = await connect_to_db()
    note = await conn.fetchrow("""
        SELECT id, note_content, content_type, file_id, caption, forward_chat_id, forward_message_id
        FROM notes WHERE id = $1
    """, note_id)
    await conn.close()
    return note



@router.message(F.text.in_({'Show my notes'}))
async def show_notes(message: Message, state: FSMContext):
    user_id = message.from_user.id
    conn = await connect_to_db()

    notes = await conn.fetch("""
        SELECT n.id, n.note_content, n.content_type, n.file_id, n.caption, n.forward_chat_id, n.forward_message_id, c.category_name
        FROM notes n
        JOIN categories c ON n.category_id = c.id
        WHERE n.user_id = $1
        ORDER BY n.id
        """, user_id
                             )
    await conn.close()

    if not notes:
        await message.answer('You still have no any notes.')
        return

    await state.update_data(notes=notes, current_index=0)
    await display_note(message.chat.id, notes[0], 0, len(notes), state)


async def display_note(chat_id, note, index, total, state: FSMContext = None):
    content_type = note['content_type']
    note_content = note['note_content']
    file_id = note.get('file_id')
    caption = note.get('caption', '')
    forward_message_id = note.get('forward_message_id')
    forward_chat_id = note.get('forward_chat_id')


    note_preview = "📝 "
    if 'category_name' in note:
        note_preview += f"[{note['category_name']}] "

    if content_type == 'forwarded':
        note_preview += "📎 Forwarded message"
    else:
        short_text = (note_content[:50] + "...") if note_content and len(note_content) > 50 else (
                    note_content or "Empty note")
        note_preview += short_text

    try:
        # Send note
        if content_type == 'forwarded' and forward_chat_id and forward_message_id:
            try:

                await bot.copy_message(
                    chat_id=chat_id,
                    from_chat_id=forward_chat_id,
                    message_id=forward_message_id
                )
            except Exception as e:
                logging.error(f"Error copying message: {e}")

                if file_id:
                    if content_type == 'photo':
                        await bot.send_photo(chat_id, file_id, caption=note_content or None)
                    elif content_type == 'video':
                        await bot.send_video(chat_id, file_id, caption=note_content or None)
                    elif content_type == 'document':
                        await bot.send_document(chat_id, file_id, caption=note_content or None)
                    elif content_type == 'audio':
                        await bot.send_audio(chat_id, file_id, caption=note_content or None)
                    elif content_type == 'voice':
                        await bot.send_voice(chat_id, file_id, caption=note_content or None)
                    elif content_type == 'sticker':
                        await bot.send_sticker(chat_id, file_id)
                else:
                    await bot.send_message(chat_id, note_content or "Forwarded message (content not available)")

        elif content_type == 'text':
            await bot.send_message(chat_id, note_content or "Empty text note")

        elif content_type == 'photo' and file_id:
            await bot.send_photo(chat_id, file_id, caption=caption or None)

        elif content_type == 'video' and file_id:
            await bot.send_video(chat_id, file_id, caption=caption or None)

        elif content_type == 'document' and file_id:
            await bot.send_document(chat_id, file_id, caption=caption or None)

        elif content_type == 'audio' and file_id:
            await bot.send_audio(chat_id, file_id, caption=caption or None)

        elif content_type == 'voice' and file_id:
            await bot.send_voice(chat_id, file_id, caption=caption or None)

        elif content_type == 'sticker' and file_id:
            await bot.send_sticker(chat_id, file_id)

        else:
            await bot.send_message(chat_id, note_content or "Note (content not available)")

    except Exception as e:
        await bot.send_message(chat_id, f'⚠️ Error displaying note: {str(e)[:50]}')
        logging.error(f'Error displaying note: {e}')


    buttons = [
        [
            InlineKeyboardButton(text="🗑️ Delete", callback_data=f"delete_note_{note['id']}")
        ],
        [
            InlineKeyboardButton(text="⬅️ Back", callback_data=f"note_nav_{index - 1}"),
            InlineKeyboardButton(text=f"{index + 1}/{total}", callback_data="note_count"),
            InlineKeyboardButton(text="➡️ Next", callback_data=f"note_nav_{index + 1}")
        ]
    ]
    markup = InlineKeyboardMarkup(inline_keyboard=buttons)


    await bot.send_message(chat_id, note_preview, reply_markup=markup)



@router.callback_query(F.data.startswith('send_note_'))
async def send_note_handler(callback: CallbackQuery, state: FSMContext):
    note_id = int(callback.data.split('_')[-1])
    note = await get_note_by_id(note_id)

    if not note:
        await callback.answer("Note not found.")
        return


    data = await state.get_data()
    notes = data.get('notes', [])


    index = next((i for i, n in enumerate(notes) if n['id'] == note_id), 0)

    await display_note(callback.message.chat.id, note, index, len(notes), state)
    await callback.answer()



@router.callback_query(F.data.startswith('delete_note_'))
async def delete_note(callback: CallbackQuery, state: FSMContext):
    note_id = int(callback.data.split("_")[-1])
    conn = await connect_to_db()
    await conn.execute('DELETE FROM notes WHERE id=$1', note_id)
    await conn.close()

    data = await state.get_data()
    notes = data.get('notes', [])
    notes = [n for n in notes if n['id'] != note_id]
    current_index = data.get("current_index", 0)

    if not notes:
        await callback.message.edit_text('Note deleted. No more notes.')
        await state.clear()
        return


    new_index = min(current_index, len(notes) - 1)
    await state.update_data(notes=notes, current_index=new_index)


    await callback.message.delete()
    await display_note(callback.message.chat.id, notes[new_index], new_index, len(notes), state)
    await callback.answer("Note deleted!")



@router.callback_query(F.data.startswith('note_nav_'))
async def navigate_notes(callback: CallbackQuery, state: FSMContext):
    try:
        index = int(callback.data.split("_")[-1])
    except ValueError:
        await callback.answer('Error with the page number')
        return

    data = await state.get_data()
    notes = data.get("notes", [])

    if 0 <= index < len(notes):

        await callback.message.delete()
        await display_note(callback.message.chat.id, notes[index], index, len(notes), state)
        await state.update_data(current_index=index)
    else:
        await callback.answer('No more notes in this direction')



@router.callback_query(F.data == "note_count")
async def handle_note_count(callback: CallbackQuery):
    await callback.answer()



@router.callback_query(F.data.startswith('note_cat_'))
async def show_category_notes(callback: CallbackQuery, state: FSMContext):
    category_id = int(callback.data.split("_")[-1])
    user_id = callback.from_user.id

    conn = await connect_to_db()
    category = await conn.fetchrow("SELECT category_name FROM categories WHERE id = $1", category_id)

    notes = await conn.fetch("""
        SELECT id, note_content, content_type, file_id, caption, forward_chat_id, forward_message_id
        FROM notes 
        WHERE user_id = $1 AND category_id = $2
        ORDER BY id
        """, user_id, category_id)

    await conn.close()

    if not notes:
        await callback.message.edit_text(f'No notes in category "{category["category_name"]}"')
        return

    await state.update_data(notes=notes, current_index=0, category_name=category["category_name"])
    await callback.message.delete()  # Удаляем сообщение с категориями
    await display_note(callback.message.chat.id, notes[0], 0, len(notes), state)

# #Handler for search button
@router.message(F.text.in_({'Search'}))
async def search_note(message: types.Message, state: FSMContext):
    await state.set_state(CategoryForm.waiting_for_search)
    await message.answer('What are you searching for?')


@router.message(StateFilter(CategoryForm.waiting_for_search))
async def search_note_query(message: types.Message, state: FSMContext):
    search_query = message.text
    user_id = message.from_user.id

    if not search_query:
        await message.answer('Can not be empty. Please, try again.')
        return

    await state.update_data(query=search_query, page=0)
    await search_results_page(message, state)


async def search_results_page(message: Message or CallbackQuery, state: FSMContext):
    data = await state.get_data()
    search_query = data.get("query")
    page = data.get("page", 0)
    per_page = 5


    if isinstance(message, Message):
        user_id = message.from_user.id
        chat_id = message.chat.id
    else:
        user_id = message.from_user.id
        chat_id = message.message.chat.id
        await message.answer()

    conn = await connect_to_db()

    total_count = await conn.fetchval('''
        SELECT COUNT(*) 
        FROM notes n
        JOIN categories c ON n.category_id = c.id
        WHERE n.user_id = $1 
        AND (
            n.note_content ILIKE $2 
            OR n.caption ILIKE $2
        )
    ''', user_id, f'%{search_query}%')

    search_results = await conn.fetch('''
        SELECT n.id, n.note_content, n.content_type, n.file_id, c.category_name, n.caption, 
               n.forward_chat_id, n.forward_message_id
        FROM notes n
        JOIN categories c ON n.category_id = c.id
        WHERE n.user_id = $1 
        AND (
            n.note_content ILIKE $2 
            OR n.caption ILIKE $2
        )
        ORDER BY n.id DESC
        LIMIT $3 OFFSET $4
    ''', user_id, f'%{search_query}%', per_page, page * per_page)

    await conn.close()

    if not search_results and page == 0:
        if isinstance(message, Message):
            await message.answer(f"Nothing found on '{search_query}'")
        else:
            await bot.send_message(chat_id, f"Nothing found on '{search_query}'")
        await state.clear()
        return

    #Current page and total number of pages
    max_page = (total_count - 1) // per_page if total_count > 0 else 0


    info_message = f"Search result '{search_query}' (page {page + 1}/{max_page + 1}, total found: {total_count}):"
    if isinstance(message, Message):
        await message.answer(info_message)
    else:
        await bot.send_message(chat_id, info_message)

    notes_with_index = []
    for i, note in enumerate(search_results):
        notes_with_index.append({
            'id': note['id'],
            'note_content': note['note_content'],
            'content_type': note['content_type'],
            'file_id': note['file_id'],
            'caption': note['caption'],
            'category_name': note['category_name'],
            'forward_chat_id': note['forward_chat_id'],
            'forward_message_id': note['forward_message_id']
        })

    await state.update_data(notes=notes_with_index)

    for i, note in enumerate(notes_with_index):
        await display_note(chat_id, note, i, len(notes_with_index), state)

    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text="⬅️ Back", callback_data="search_prev"))
    if page < max_page:
        nav_buttons.append(InlineKeyboardButton(text="Forward ➡️", callback_data="search_next"))

    if nav_buttons:
        nav_keyboard = InlineKeyboardMarkup(inline_keyboard=[nav_buttons])
        if isinstance(message, Message):
            await message.answer("Nav through the results:", reply_markup=nav_keyboard)
        else:
            await bot.send_message(chat_id, "Nav through the results:", reply_markup=nav_keyboard)

    await state.clear()

    if isinstance(message, Message):
        await message.answer('Search is completed. For new query press the button "Search".')
    else:
        await bot.send_message(chat_id, 'Search is completed. For new query press the button "Search".')

#Buttons for navigation in search
@router.callback_query(F.data == "search_prev")
async def process_search_prev(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    current_page = data.get("page", 0)
    if current_page > 0:
        await state.update_data(page=current_page - 1)
    await search_results_page(callback, state)


@router.callback_query(F.data == "search_next")
async def process_search_next(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    current_page = data.get("page", 0)
    await state.update_data(page=current_page + 1)
    await search_results_page(callback, state)


async def main():
    print("Bot has been started!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())