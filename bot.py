import os
import re
import asyncio
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

import lyricsgenius

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
GENIUS_TOKEN = os.getenv("GENIUS_TOKEN")
CHANNEL_RU = "@airears"
CHANNEL_UZ = "@airMusik_uz"

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

class PostState(StatesGroup):
    waiting_for_lang = State()
    waiting_for_action = State()
    waiting_for_text = State()

def get_footer(lang: str):
    if lang == "uz":
        return "\n\n<b><a href='https://t.me/airMusic_uz'>Obuna b’olish</a></b>"
    return "\n\n<b><a href='https://t.me/airears'>Подписаться</a> | <a href='https://t.me/rec_airbot'>Порекомендовать трек</a></b>"

def build_caption(lang: str, title: str, lyrics: str) -> str:
    if lang == "uz":
        header = f"• Musiqa nomi — {title}\n\nMusiqa teksti:\n<blockquote expandable>"
    else:
        header = f"• Трек — {title}\n\nТекст:\n<blockquote expandable>"
    
    footer = get_footer(lang)
    max_len = 1024 - len(header) - len(footer) - len("</blockquote>") - 5
    lyrics = (lyrics[:max_len] + "...") if len(lyrics) > max_len else lyrics
    return f"{header}{lyrics}</blockquote>{footer}"

def fetch_lyrics(title, artist):
    try:
        genius = lyricsgenius.Genius(GENIUS_TOKEN, timeout=10, verbose=False)
        song = genius.search_song(title, artist)
        return re.sub(r'(\d*Embed$|^.*Lyrics\n?)', '', song.lyrics).strip() if song and song.lyrics else "Текст не найден."
    except: return "Текст не найден."

@dp.message(F.text == "/start")
async def cmd_start(message: Message):
    await message.answer("👋 Привет! Пришли мне аудиофайл, и я оформлю его для канала.")

@dp.message(F.audio)
async def handle_audio(message: Message, state: FSMContext):
    await state.update_data(file_id=message.audio.file_id, title=message.audio.title or "Unknown", artist=message.audio.performer or "")
    await state.set_state(PostState.waiting_for_lang)
    await message.reply("Куда публикуем? Напиши /ru или /uz")

@dp.message(PostState.waiting_for_lang, F.text.in_({"/ru", "/uz"}))
async def set_lang(message: Message, state: FSMContext):
    lang = message.text[1:]
    data = await state.get_data()
    lyrics = await asyncio.to_thread(fetch_lyrics, data['title'], data['artist'])
    
    caption = build_caption(lang, data['title'], lyrics)
    await state.update_data(lang=lang, caption=caption)
    
    await message.answer_audio(audio=data['file_id'], caption=caption)
    await message.answer("Пример готов.\n/y — публ., /n — отмена, /text — изменить текст.")
    await state.set_state(PostState.waiting_for_action)

@dp.message(PostState.waiting_for_action, F.text == "/text")
async def ask_text(message: Message, state: FSMContext):
    await state.set_state(PostState.waiting_for_text)
    await message.reply("Пришли текст:")

@dp.message(PostState.waiting_for_text)
async def get_text(message: Message, state: FSMContext):
    data = await state.get_data()
    caption = build_caption(data['lang'], data['title'], message.text)
    await state.update_data(caption=caption)
    await message.answer_audio(audio=data['file_id'], caption=caption)
    await state.set_state(PostState.waiting_for_action)

@dp.message(PostState.waiting_for_action, F.text == "/y")
async def publish(message: Message, state: FSMContext):
    data = await state.get_data()
    chat = CHANNEL_RU if data['lang'] == "ru" else CHANNEL_UZ
    try:
        await bot.send_audio(chat, audio=data['file_id'], caption=data['caption'])
        await message.reply(f"✅ Опубликовано в {chat}!")
    except Exception as e:
        await message.reply(f"Ошибка публикации: {e}")
    await state.clear()

@dp.message(PostState.waiting_for_action, F.text == "/n")
async def cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.reply("🚫 Отменено.")

if __name__ == "__main__":
    asyncio.run(dp.start_polling(bot))
