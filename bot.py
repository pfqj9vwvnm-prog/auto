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

# Загрузка переменных окружения (для локальных тестов)
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
GENIUS_TOKEN = os.getenv("GENIUS_TOKEN")  # Токен от Genius API для текстов
CHANNEL_ID = "@airears"
COVER_PATH = "cover.jpg"

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# Состояния для FSM
class PostState(StatesGroup):
    waiting_for_action = State()

def clean_lyrics(text: str) -> str:
    """Очищает текст от мусора, который отдает Genius API."""
    if not text:
        return "Текст не найден."
    # Убираем первую строку вида "12 ContributorsНазвание Lyrics"
    text = re.sub(r'^.*Lyrics\n?', '', text, 1)
    # Убираем "Embed" и цифры в конце
    text = re.sub(r'\d*Embed$', '', text)
    return text.strip()

def fetch_lyrics_sync(title: str, artist: str) -> str:
    """Синхронная функция поиска текста (будет запущена в отдельном потоке)."""
    if not GENIUS_TOKEN:
        return "Текст не найден (нет токена Genius)."
    try:
        genius = lyricsgenius.Genius(GENIUS_TOKEN, timeout=10, retries=2, verbose=False)
        song = genius.search_song(title, artist)
        if song and song.lyrics:
            return clean_lyrics(song.lyrics)
        return "Текст не найден."
    except Exception as e:
        print(f"Ошибка поиска текста: {e}")
        return "Текст не найден."

def edit_metadata(file_path: str, new_title: str):
    """Изменение метаданных MP3 файла."""
    try:
        audio = MP3(file_path, ID3=ID3)
    except ID3Error:
        audio = MP3(file_path)
        audio.add_tags()

    # Удаляем старые теги
    audio.delete()
    audio.tags = ID3()

    # Добавляем новые
    audio.tags.add(TIT2(encoding=3, text=new_title))
    audio.tags.add(TPE1(encoding=3, text="ᴛᴩᴇᴋи ʙ ᴛᴦᴋ - @ᴀɪʀᴇᴀʀs"))

    # Добавляем обложку, если файл существует
    if os.path.exists(COVER_PATH):
        with open(COVER_PATH, 'rb') as cover_img:
            audio.tags.add(APIC(
                encoding=3, 
                mime='image/jpeg', 
                type=3, 
                desc='Cover',
                data=cover_img.read()
            ))
    
    audio.save(v2_version=3)

@dp.message(F.audio)
async def handle_audio(message: Message, state: FSMContext):
    # Если бот уже ждет ответа по другому треку
    if await state.get_state() == PostState.waiting_for_action:
        await message.reply("Сначала заверши работу с предыдущим треком: напиши /y или /n")
        return

    audio_msg = message.audio
    
    # Проверка размера файла (Telegram Bot API лимит 20 МБ на скачивание)
    if audio_msg.file_size > 20 * 1024 * 1024:
        await message.reply("Файл слишком большой (лимит 20 МБ).")
        return

    await message.reply("Начинаю обработку... ⏳")

    # Оригинальные названия для поиска текста
    original_title = audio_msg.title or audio_msg.file_name or "Unknown"
    if original_title.endswith('.mp3'):
        original_title = original_title[:-4]
    original_artist = audio_msg.performer or ""

    # Новое название
    new_title = original_title 

    # Пути для сохранения
    file_id = audio_msg.file_id
    local_filepath = f"{file_id}.mp3"

    try:
        # Скачиваем файл
        file_info = await bot.get_file(file_id)
        await bot.download_file(file_info.file_path, local_filepath)

        # Редактируем метаданные в отдельном потоке (чтобы не блокировать асинхронность)
        await asyncio.to_thread(edit_metadata, local_filepath, new_title)

        # Ищем текст песни в отдельном потоке
        lyrics = await asyncio.to_thread(fetch_lyrics_sync, original_title, original_artist)

        # Формируем пост. Лимит подписи в Telegram - 1024 символа
        header = f"• Трек — {new_title}\n\n<blockquote expandable>Текст:\n"
        footer = "</blockquote>\n\n<b>@airears</b>"
        
        # Обрезка текста, если он не влезает в лимиты
        max_lyrics_len = 1024 - len(header) - len(footer) - 5
        if len(lyrics) > max_lyrics_len:
            lyrics = lyrics[:max_lyrics_len] + "..."
            
        caption = f"{header}{lyrics}{footer}"

        # Отправляем превью пользователю
        preview_msg = await message.answer_audio(
            audio=FSInputFile(local_filepath),
            caption=caption,
            title=new_title,
            performer="ᴛᴩᴇᴋи ʙ ᴛᴦᴋ - @ᴀɪʀᴇᴀʀs"
        )
        
        await message.answer("👆 Вот так будет выглядеть пост.\n\nОтправь:\n/y — чтобы опубликовать в канал\n/n — чтобы отменить")

        # Сохраняем данные в FSM
        await state.set_state(PostState.waiting_for_action)
        await state.update_data(
            local_filepath=local_filepath,
            caption=caption,
            title=new_title
        )

    except Exception as e:
        await message.reply(f"Произошла ошибка при обработке: {e}")
        if os.path.exists(local_filepath):
            os.remove(local_filepath)

@dp.message(F.text == "/y", PostState.waiting_for_action)
async def approve_post(message: Message, state: FSMContext):
    data = await state.get_data()
    local_filepath = data['local_filepath']
    
    try:
        # Отправляем в канал
        await bot.send_audio(
            chat_id=CHANNEL_ID,
            audio=FSInputFile(local_filepath),
            caption=data['caption'],
            title=data['title'],
            performer="ᴛᴩᴇᴋи ʙ ᴛᴦᴋ - @ᴀɪʀᴇᴀʀs"
        )
        await message.reply("✅ Успешно опубликовано в канал!")
    except Exception as e:
        await message.reply(f"❌ Ошибка публикации. Проверь, является ли бот админом в канале.\nТекст ошибки: {e}")
    finally:
        # Очистка
        if os.path.exists(local_filepath):
            os.remove(local_filepath)
        await state.clear()

@dp.message(F.text == "/n", PostState.waiting_for_action)
async def reject_post(message: Message, state: FSMContext):
    data = await state.get_data()
    local_filepath = data['local_filepath']
    
    # Очистка локального файла
    if os.path.exists(local_filepath):
        os.remove(local_filepath)
        
    await state.clear()
    await message.reply("🚫 Публикация отменена. Жду следующий трек.")

@dp.message(PostState.waiting_for_action)
async def wrong_action_handler(message: Message):
    await message.reply("Пожалуйста, ответь /y (публиковать) или /n (отменить).")

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    print("Бот запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
