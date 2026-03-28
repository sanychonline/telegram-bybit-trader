import os
import asyncio
from classes.config import TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_CHAT_ID, DATA_STORAGE_DIR
from classes.reporting.health_state import touch
from classes.telegram.parser import classify_message
from telethon import TelegramClient, events


class TelegramService:
    def __init__(self, worker, logger):
        self.worker = worker
        self.logger = logger

        self.api_id = TELEGRAM_API_ID
        self.api_hash = TELEGRAM_API_HASH
        self.chat_id = TELEGRAM_CHAT_ID

        os.makedirs(DATA_STORAGE_DIR, exist_ok=True)

        self.session_path = f"{DATA_STORAGE_DIR}/session"
        self.client = TelegramClient(self.session_path, self.api_id, self.api_hash)

        self.is_ready = False
        self.startup_last_message_id = 0
        self.seen_message_ids = set()

    async def _mark_seen(self, message_id):
        if message_id is None:
            return False
        if message_id in self.seen_message_ids:
            return False
        self.seen_message_ids.add(message_id)
        return True

    async def _process_message(self, message, source="telegram"):
        message_id = getattr(message, "id", None)
        if message_id is None:
            return

        if message_id <= self.startup_last_message_id:
            self.logger.debug(f"Telegram message ignored as stale | message_id={message_id}")
            return

        if not await self._mark_seen(message_id):
            return

        text = message.text or ""
        classification = classify_message(text)

        if classification["type"] == "ignored":
            self.logger.debug(f"Telegram message ignored | message_id={message_id}")
            return

        self.logger.debug(
            f"Telegram message routed | message_id={message_id} | type={classification['type']}"
        )
        self.logger.debug(f"Message text: {text}")
        touch("telegram")

        await self.worker.handle_message(message, source=source)

    async def start(self):
        await self.client.start()
        self.is_ready = True
        latest_messages = [message async for message in self.client.iter_messages(self.chat_id, limit=1)]
        self.startup_last_message_id = latest_messages[0].id if latest_messages else 0
        touch("telegram")
        self.logger.info("Telegram client started")
        self.logger.debug(
            f"Telegram startup state | startup_last_message_id={self.startup_last_message_id}"
        )

        async def keepalive_loop():
            while True:
                try:
                    await self.client.get_me()
                    touch("telegram")
                    await asyncio.sleep(30)
                except Exception as e:
                    self.logger.error(f"Telegram keepalive error: {e}")
                    await asyncio.sleep(10)

        async def poll_new_messages_loop():
            while True:
                try:
                    messages = []
                    async for message in self.client.iter_messages(self.chat_id, limit=20):
                        if getattr(message, "id", 0) > self.startup_last_message_id:
                            messages.append(message)

                    for message in reversed(messages):
                        await self._process_message(message, source="telegram")

                    await asyncio.sleep(2)
                except Exception as e:
                    self.logger.error(f"Telegram polling error: {e}")
                    await asyncio.sleep(5)

        @self.client.on(events.NewMessage(chats=self.chat_id))
        async def handler(event):
            try:
                await self._process_message(event.message, source="telegram")

            except Exception as e:
                self.logger.error(f"Telegram handler error: {e}")

        await asyncio.gather(
            self.client.run_until_disconnected(),
            keepalive_loop(),
            poll_new_messages_loop(),
        )

    async def send_message(self, text):
        if not self.is_ready:
            raise Exception("Telegram not ready")

        return await self.client.send_message(self.chat_id, text)
