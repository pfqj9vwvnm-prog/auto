@dp.message(F.audio)
async def handle_audio(message: Message):
    user_id = message.from_user.id
    lang = user_langs.get(user_id, "ru")
    
    audio = message.audio
    title = audio.title or audio.file_name.replace('.mp3', '')
    
    # Бот берет длительность прямо из аудиофайла (в секундах)
    duration_seconds = audio.duration or 0 
    
    local_path = f"{audio.file_id}.mp3"
    
    try:
        file_info = await bot.get_file(audio.file_id)
        await bot.download_file(file_info.file_path, local_path)
        
        performer = "ʍузыᴋᴀᴧᴀᴩ ᴋᴀнᴀᴧи: @ᴀɪʀᴍᴜsɪᴋ_ᴜᴢ" if lang == "uz" else "ᴛᴩᴇᴋи ʙ ᴛᴦᴋ - @ᴀɪʀᴇᴀʀs"
        await asyncio.to_thread(edit_metadata, local_path, title, lang)
        
        # Передаем реальную длительность трека в шаблон
        caption = get_caption(lang, title, duration_seconds)
        
        await post_queue.put({
            'file_path': local_path,
            'caption': caption,
            'title': title,
            'performer': performer,
            'lang': lang
        })
        
        q_size = post_queue.qsize()
        await message.reply(f"📥 Трек добавлен в очередь! Позиция: {q_size}. Время трека: {format_duration(duration_seconds)}")
    except Exception as e:
        await message.reply(f"❌ Ошибка обработки: {e}")
        if os.path.exists(local_path):
            os.remove(local_path)
