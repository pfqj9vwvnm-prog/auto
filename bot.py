import os
import re
import asyncio
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, FSInputFile
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from mutagen.mp3 import MP3
from mutagen.id3 import ID3, TIT2, TPE1, APIC
from mutagen.id3 import error as ID3Error

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_RU = "@airears"
CHANNEL_UZ = "@airMusik_uz"
COVER_PATH = "cover.jpeg"

# 1. СНАЧАЛА создаем бота и диспетчер (dp)
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

post_queue = asyncio.Queue()
post_delay = 60 
user_langs = {}

def format_duration(seconds: int) -> str:
    """Конвертирует секунды из файла в формат MM:SS (например, 00:06)"""
    if not seconds:
        return "00:00"
    m = seconds // 60
    s = seconds % 60
    return f"{m:02d}:{s:02d}"

def get_caption(lang: str, title: str, duration: int) -> str:
    dur_str = format_duration(duration)
    if lang == "uz":
        return f"▶︎ {dur_str}  <a href='https://t.me/airmusic_uz'>🎧 * {title}</a>"
    else:
        footer = "\n\n<b><a href='https://t.me/airears'>Подписаться</a> | <a href='https://t.me/rec_airbot'>Порекомендовать трек</a></b>"
        return f"• Трек — {title}\n\nТекст отсутствует.{footer}"

def edit_metadata(file_path: str, new_title: str, lang: str):
    try:
        audio = MP3(file_path, ID3=ID3)
    except ID3Error:
        audio = MP3(file_path)
        audio.add_tags()
    audio.delete()
    audio.tags = ID3()
    audio.tags.add(TIT2(encoding=3, text=new_title))
    
    performer = "ʍузыᴋᴀᴧᴀᴩ ᴋᴀнᴀᴧи: @ᴀɪʀᴍᴜsɪᴋ_ᴜᴢ" if lang == "uz" else "ᴛᴩᴇᴋи ʙ ᴛᴦᴋ - @ᴀɪʀᴇᴀʀs"
    audio.tags.add(TPE1(encoding=3, text=performer))
    
    if os.path.exists(COVER_PATH):
        with open(COVER_PATH, 'rb') as f:
            audio.tags.add(APIC(encoding=3, mime='image/jpeg', type=3, desc='Cover', data=f.read()))
    audio.save(v2_version=3)

async def queue_worker():
    global post_delay
    while True:
        task = await post_queue.get()
        try:
            chat = CHANNEL_RU if task['lang'] == "ru" else CHANNEL_UZ
            await bot.send_audio(
                chat_id=chat,
                audio=FSInputFile(task['file_path']),
                caption=task['caption'],
                title=task['title'],
                performer=task['performer']
            )
        except Exception as e:
            print(f"Ошибка отправки из очереди: {e}")
        finally:
            if os.path.exists(task['file_path']):
                try:
                    os.remove(task['file_path'])
                except:
                    pass
            post_queue.task_done()
        await asyncio.sleep(post_delay)

# 2. ПОТОМ идут все обработчики (теперь dp уже существует)
@dp.message(F.text == "/start")
async def cmd_start(message: Message):
    current_mode = user_langs.get(message.from_user.id, "ru")
    await message.answer(
        f"👋 Привет! Твой текущий режим: <b>{current_mode.upper()}</b>.\n\n"
        "📌 <b>Команды:</b>\n"
        "🇷🇺 /ru — переключить на русский (@airears)\n"
        "🇺🇿 /uz — переключить на узбекский (@airMusik_uz)\n"
        f"⏱ `/cd [сек]` — изменить интервал очереди (сейчас: <code>{post_delay}</code> сек)\n\n"
        "Присылай аудиофайлы (можно много), бот сам возьмет длительность, оформит трек и поставит в очередь!"
    )

@dp.message(F.text.in_({"/ru", "/uz"}))
async def set_channel_mode(message: Message):
    lang = message.text[1:]
    user_langs[message.from_user.id] = lang
    channel = CHANNEL_RU if lang == "ru" else CHANNEL_UZ
    await message.reply(f"✅ Режим изменен на <b>{lang.upper()}</b>.\nКанал: <b>{channel}</b>")

@dp.message(F.text.startswith("/cd"))
async def change_delay(message: Message):
    global post_delay
    parts = message.text.split()
    if len(parts) > 1 and parts[1].isdigit():
        post_delay = int(parts[1])
        await message.reply(f"⏱ Задержка изменена на <b>{post_delay} сек.</b>")
    else:
        await message.reply(f"⏱ Текущая задержка: <b>{post_delay} сек.</b> (Пример: `/cd 30`)")

@dp.message(F.audio)
async def handle_audio(message: Message):
    user_id = message.from_user.id
    lang = user_langs.get(user_id, "ru")
    
    audio = message.audio
    title = audio.title or audio.file_name.replace('.mp3', '')
    duration_seconds = audio.duration or 0 
    
    local_path = f"{audio.file_id}.mp3"
    
    try:
        file_info = await bot.get_file(audio.file_id)
        await bot.download_file(file_info.file_path, local_path)
        
        performer = "ʍузыᴋᴀᴧᴀᴩ ᴋᴀнᴀᴧи: @ᴀɪʀᴍᴜsɪᴋ_ᴜᴢ" if lang == "uz" else "ᴛᴩᴇᴋи ʙ ᴛᴦᴋ - @ᴀɪʀᴇᴀʀs"
        await asyncio.to_thread(edit_metadata, local_path, title, lang)
        
        caption = get_caption(lang, title, duration_seconds)
        
        await post_queue.put({
            'file_path': local_path,
            'caption': caption,
            'title': title,
            'performer': performer,
            'lang': lang
        })
        
        q_size = post_queue.qsize()
        await message.reply(f"📥 Трек добавлен в очередь! Позиция: {q_size}. Длительность: {format_duration(duration_seconds)}")
    except Exception as e:
        await message.reply(f"❌ Ошибка обработки: {e}")
        if os.path.exists(local_path):
            os.remove(local_path)

async def main():
    asyncio.create_task(queue_worker())
    await bot.delete_webhook(drop_pending_updates=True)
    print("Бот успешно запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
