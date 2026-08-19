import os
import re
import asyncio
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, FSInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from mutagen.mp3 import MP3
from mutagen.id3 import ID3, TIT2, TPE1, APIC
from mutagen.id3 import error as ID3Error
import lyricsgenius

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
GENIUS_TOKEN = os.getenv("GENIUS_TOKEN")

CHANNEL_ID = "@airears"
COVER_PATH = "cover.jpeg"

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

class PostState(StatesGroup):
    waiting_for_action = State()
    waiting_for_text = State()

def get_footer():
    return "\n\n<b><a href='https://t.me/airears'>Подписаться</a> | <a href='https://t.me/rec_airbot'>Порекомендовать трек</a></b>"

def clean_lyrics(text: str) -> str:
    if not text: return "Текст не найден."
    text = re.sub(r'^.*Lyrics\n?', '', text, 1)
    text = re.sub(r'\d*Embed$', '', text)
    return text.strip()

def fetch_lyrics_sync(title: str, artist: str) -> str:
    if not GENIUS_TOKEN: return "Текст не найден."
    try:
        genius = lyricsgenius.Genius(GENIUS_TOKEN, timeout=10, retries=2, verbose=False)
        song = genius.search_song(title, artist)
        return clean_lyrics(song.lyrics) if song and song.lyrics else "Текст не найден."
    except Exception:
        return "Текст не найден."

def edit_metadata(file_path: str, new_title: str):
    try:
        audio = MP3(file_path, ID3=ID3)
    except ID3Error:
        audio = MP3(file_path)
        audio.add_tags()
    audio.delete()
    audio.tags = ID3()
    audio.tags.add(TIT2(encoding=3, text=new_title))
    audio.tags.add(TPE1(encoding=3, text="ᴛᴩᴇᴋи ʙ ᴛᴦᴋ - @ᴀɪʀᴇᴀʀs"))
    if os.path.exists(COVER_PATH):
        with open(COVER_PATH, 'rb') as cover_img:
            audio.tags.add(APIC(encoding=3, mime='image/jpeg', type=3, desc='Cover', data=cover_img.read()))
    audio.save(v2_version=3)

def build_caption(title: str, lyrics: str) -> str:
    """Безопасно собирает подпись, контролируя лимит Telegram (1024 символа)."""
    header = f"• Трек — {title}\n\n<blockquote expandable>Текст:\n"
    footer = get_footer()
    
    # Считаем, сколько символов остается чисто под текст песни
    max_lyrics_len = 1024 - len(header) - len(footer) - len("</blockquote>") - 5
    
    if max_lyrics_len < 50:
        max_lyrics_len = 50 # Защита от сбоев
        
    if len(lyrics) > max_lyrics_len:
        lyrics = lyrics[:max_lyrics_len] + "..."
        
    # Всегда строго добавляем закрывающий тег в конце блока цитаты
    return f"{header}{lyrics}</blockquote>{footer}"

@dp.message(F.text == "/start")
async def cmd_start(message: Message):
    await message.answer("👋 Привет! Пришли мне аудиофайл, и я оформлю его для канала @airears.")

@dp.message(F.audio)
async def handle_audio(message: Message, state: FSMContext):
    if await state.get_state():
        await message.reply("Сначала заверши работу с предыдущим треком: /y или /n")
        return

    audio_msg = message.audio
    if audio_msg.file_size > 20 * 1024 * 1024:
        await message.reply("Файл > 20 МБ.")
        return

    await message.reply("Обработка... ⏳")
    original_title = audio_msg.title or audio_msg.file_name.replace('.mp3', '')
    original_artist = audio_msg.performer or ""
    local_filepath = f"{audio_msg.file_id}.mp3"

    try:
        file_info = await bot.get_file(audio_msg.file_id)
        await bot.download_file(file_info.file_path, local_filepath)
        await asyncio.to_thread(edit_metadata, local_filepath, original_title)
        lyrics = await asyncio.to_thread(fetch_lyrics_sync, original_title, original_artist)

        caption = build_caption(original_title, lyrics)

        await message.answer_audio(audio=FSInputFile(local_filepath), caption=caption, title=original_title, performer="ᴛᴩᴇᴋи ʙ ᴛᴦᴋ - @ᴀɪʀᴇᴀʀs")
        await message.answer("👆 Пример готов.\n/y — публ.\n/n — отмена\n/text — вставить текст вручную")
        await state.set_state(PostState.waiting_for_action)
        await state.update_data(local_filepath=local_filepath, title=original_title, caption=caption)
    except Exception as e:
        await message.reply(f"Ошибка: {e}")

@dp.message(F.text == "/text", PostState.waiting_for_action)
async def ask_for_text(message: Message, state: FSMContext):
    await state.set_state(PostState.waiting_for_text)
    await message.reply("Пришли текст песни одним сообщением:")

@dp.message(PostState.waiting_for_text)
async def receive_text(message: Message, state: FSMContext):
    data = await state.get_data()
    caption = build_caption(data['title'], message.text)
    
    await message.answer_audio(audio=FSInputFile(data['local_filepath']), caption=caption, title=data['title'], performer="ᴛᴩᴇᴋи ʙ ᴛᴦᴋ - @ᴀɪʀᴇᴀʀs")
    await state.update_data(caption=caption)
    await state.set_state(PostState.waiting_for_action)
    await message.answer("✅ Текст обновлен. /y — публ., /n — отмена.")

@dp.message(F.text == "/y", PostState.waiting_for_action)
async def approve_post(message: Message, state: FSMContext):
    data = await state.get_data()
    path = data['local_filepath']
    try:
        await bot.send_audio(CHANNEL_ID, audio=FSInputFile(path), caption=data['caption'], title=data['title'], performer="ᴛᴩᴇᴋи ʙ ᴛᴦᴋ - @ᴀɪʀᴇᴀʀs")
        await message.reply("✅ Опубликовано!")
    finally:
        if os.path.exists(path): os.remove(path)
        await state.clear()

@dp.message(F.text == "/n", PostState.waiting_for_action)
async def reject_post(message: Message, state: FSMContext):
    data = await state.get_data()
    if os.path.exists(data['local_filepath']): os.remove(data['local_filepath'])
    await state.clear()
    await message.reply("🚫 Отменено.")

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
