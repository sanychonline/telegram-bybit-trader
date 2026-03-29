import os
import asyncio
from datetime import datetime, timezone, timedelta
from config import TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_CHAT_ID, DATA_TELEGRAM_SESSION_PATH
from classes.reporting.health_state import touch
from classes.telegram.parser import classify_message, parse_signal
from telethon import TelegramClient, events


MAX_BACKFILL_SIGNAL_AGE_SECONDS = 60


class TelegramService:
    def __init__(self, worker, logger, storage=None):
        self.worker = worker
        self.logger = logger
        self.is_enabled = True

        self.api_id = TELEGRAM_API_ID
        self.api_hash = TELEGRAM_API_HASH
        self.chat_id = TELEGRAM_CHAT_ID
        if storage is not None:
            self.api_id = storage.get_app_secret("telegram_api_id", TELEGRAM_API_ID)
            self.api_hash = storage.get_app_secret("telegram_api_hash", TELEGRAM_API_HASH)
            self.chat_id = storage.get_app_setting("telegram_chat_id", TELEGRAM_CHAT_ID)

        if self.api_id is None or not self.api_hash or self.chat_id is None:
            self.is_enabled = False
            self.is_ready = False
            self.logger.warning("Telegram integration is not configured; Telegram loop will stay disabled")
            return

        self.api_id = int(self.api_id)
        self.chat_id = int(self.chat_id)

        os.makedirs(os.path.dirname(DATA_TELEGRAM_SESSION_PATH), exist_ok=True)

        self.session_path = DATA_TELEGRAM_SESSION_PATH
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

        if source == "telegram_backfill" and classification["type"] == "signal":
            message_date = getattr(message, "date", None)
            if message_date is not None:
                try:
                    if message_date.tzinfo is None:
                        message_date = message_date.replace(tzinfo=timezone.utc)
                    else:
                        message_date = message_date.astimezone(timezone.utc)
                    age = datetime.now(timezone.utc) - message_date
                    if age > timedelta(seconds=MAX_BACKFILL_SIGNAL_AGE_SECONDS):
                        self.logger.info(
                            f"Telegram backfill signal skipped as stale | message_id={message_id} "
                            f"| age_sec={int(age.total_seconds())}"
                        )
                        if self.worker and getattr(self.worker, "storage", None) is not None:
                            self.worker.storage.record_signal_event({
                                "message_id": message_id,
                                "symbol": classification["payload"].get("symbol"),
                                "side": classification["payload"].get("side"),
                                "source": source,
                                "created_at": message_date.isoformat(),
                                "status": "skipped",
                                "reason": "stale_backfill_signal",
                                "stale_backfill_age_sec": int(age.total_seconds()),
                            })
                        return
                except Exception as e:
                    self.logger.warning(
                        f"Unable to evaluate backfill age; processing anyway | message_id={message_id} | error={e}"
                    )

        touch("telegram")

        await self.worker.handle_message(message, source=source)

    async def start(self):
        if not self.is_enabled:
            return

        await self.client.start()
        self.is_ready = True
        stored_last_message_id = 0
        if self.worker and getattr(self.worker, "storage", None) is not None:
            try:
                stored_last_message_id = int(self.worker.storage.get_latest_signal_message_id() or 0)
            except Exception:
                stored_last_message_id = 0

        self.startup_last_message_id = stored_last_message_id
        backlog_messages = []
        async for message in self.client.iter_messages(self.chat_id, limit=100):
            message_id = getattr(message, "id", 0) or 0
            if message_id <= self.startup_last_message_id:
                break
            backlog_messages.append(message)

        for message in reversed(backlog_messages):
            await self._process_message(message, source="telegram_backfill")

        async for message in self.client.iter_messages(self.chat_id, limit=100):
            text = message.text or ""
            signal = parse_signal(text)
            if not signal:
                continue
            self.worker.storage.record_signal_event({
                "message_id": getattr(message, "id", None),
                "symbol": signal.get("symbol"),
                "side": signal.get("side"),
                "source": "telegram_history_sync",
                "created_at": message.date.isoformat() if getattr(message, "date", None) else None,
            })

        touch("telegram")
        self.logger.info("Telegram client started")
        self.logger.debug(
            f"Telegram startup state | startup_last_message_id={self.startup_last_message_id} "
            f"| backlog_processed={len(backlog_messages)}"
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
