import logging
import requests
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import CommandStart
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from lxml import html
from aiogram import Bot, Dispatcher, types, F
from aiogram import Router
import asyncio
import hashlib
import os
from dotenv import load_dotenv
from io import BytesIO

load_dotenv()

API_TOKEN = os.getenv("TOKEN")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

URL = os.getenv("URL")
BASE_URL = "/".join(URL.split("/")[:3])
XPATH = os.getenv("XPATH")

state_file = './data/schedule_state.txt'
subscribers_file = './data/subscribers.txt'

# Инициализация бота и диспетчера
bot = Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
router = Router()
dp = Dispatcher()


def fetch_schedule():
    response = requests.get(URL)
    tree = html.fromstring(response.content)

    items = tree.xpath(XPATH)

    unique_links = set()
    schedule = []

    for item in items:
        text = item.text_content().strip()
        link = item.xpath('./@href')
        if link and text:
            full_link = f'{BASE_URL}{link[0]}'

            if 'Расписание' in text and full_link not in unique_links:
                unique_links.add(full_link)
                schedule.append((text, full_link))

    return schedule


def get_schedule_hash(schedule):
    links = [link for _, link in schedule]
    return hashlib.md5("\n".join(links).encode()).hexdigest()


async def send_telegram_notification(schedule_items):
    subscribers = load_subscribers()

    for user_id in subscribers:
        media_group = []
        first_file = True
        text_message = ""

        for text, link in schedule_items:
            text_message += f"📚 <a href=\"{link}\">{text}</a>\n"

        for text, link in schedule_items:
            try:
                file_response = requests.get(link)
                if file_response.status_code == 200:
                    file_content = BytesIO(file_response.content)
                    file_content.seek(0)
                    filename = link.split("/")[-1]

                    if any(filename.endswith(ext) for ext in [".pdf", ".doc", ".docx", ".xlsx", ".xls"]):
                        if first_file:
                            media_group.append(
                                types.InputMediaDocument(
                                    media=types.BufferedInputFile(file_content.read(), filename=filename),
                                    caption=text_message,
                                    parse_mode="HTML"
                                )
                            )
                            first_file = False
                        else:
                            media_group.append(
                                types.InputMediaDocument(
                                    media=types.BufferedInputFile(file_content.read(), filename=filename)
                                )
                            )
            except Exception as e:
                print(f"Ошибка при скачивании или подготовке файла: {e}")

        if media_group:
            try:
                await bot.send_media_group(user_id, media=media_group)
            except Exception as e:
                print(f"Ошибка при отправке медиагруппы пользователю {user_id}: {e}")



def load_previous_state():
    if os.path.exists(state_file):
        with open(state_file, 'r') as f:
            return f.read().strip()
    return ""


def save_current_state(schedule_hash):
    with open(state_file, 'w') as f:
        f.write(schedule_hash)


def load_subscribers():
    if os.path.exists(subscribers_file):
        with open(subscribers_file, 'r') as f:
            return [line.strip() for line in f.readlines()]
    return []


def remove_subscriber(user_id):
    if os.path.exists(subscribers_file):
        with open(subscribers_file, 'r') as f:
            subscribers = f.readlines()
        with open(subscribers_file, 'w') as f:
            for subscriber in subscribers:
                if subscriber.strip() != str(user_id):
                    f.write(subscriber)


def is_subscribed(user_id):
    if os.path.exists(subscribers_file):
        with open(subscribers_file, 'r') as f:
            subscribers = f.readlines()
            return f"{user_id}\n" in subscribers
    return False


def save_subscriber(user_id):
    with open(subscribers_file, 'a') as f:
        f.write(f"{user_id}\n")


async def cmd_start(message: types.Message):
    user_id = str(message.from_user.id)
    chat_id = str(message.chat.id)

    if message.chat.type in ['group', 'supergroup']:
        id_to_save = chat_id
    else:
        id_to_save = user_id

    if is_subscribed(id_to_save):
        remove_subscriber(id_to_save)
        reply_message = "Вы отписались от уведомлений о изменениях расписания."
    else:
        save_subscriber(id_to_save)
        reply_message = "Привет! Вы успешно подписались на уведомления о изменениях расписания."

    if message.chat.type in ['group', 'supergroup']:
        await message.answer(reply_message)
    else:
        await bot.send_message(user_id, reply_message)


async def check_schedule_change():
    current_schedule = fetch_schedule()
    current_schedule_hash = get_schedule_hash(current_schedule)

    previous_state = load_previous_state()

    if current_schedule_hash != previous_state:
        await send_telegram_notification(current_schedule)
        save_current_state(current_schedule_hash)


def setup_scheduler():
    scheduler = AsyncIOScheduler()
    scheduler.add_job(check_schedule_change, "interval", minutes=3)  # Каждые 3 минуты
    scheduler.start()


async def main():
    setup_scheduler()
    await dp.start_polling(
        bot,
        allowed_updates=["callback_query", "message", "inline_query", "my_chat_member"],
    )


if __name__ == '__main__':
    dp.include_router(router)
    router.message.register(cmd_start, CommandStart())
    asyncio.run(main())
