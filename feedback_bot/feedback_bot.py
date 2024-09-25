import logging
import random
import datetime
from typing import List, Dict, Union, Optional

from prometheus_client import Gauge, Counter, start_http_server
from telethon import events, TelegramClient, Button


start_time = Gauge("feedbackbot_start_unixtime", "Unix timestamp of the last time the bot was started")
latest_msg = Gauge(
    "feedbackbot_latest_msg_unixtime",
    "Unix timestamp of the last time a message was reformatted by the bot",
    labelnames=["channel_id", "reformat_type"]
)
latest_press = Gauge(
    "feedbackbot_button_press_unixtime",
    "Unix timestamp of the last time a feedback button was pressed",
    labelnames=["channel_id", "option"]
)
msg_count = Counter(
    "feedbackbot_msg_total",
    "Total number of messages reformatted by the bot to add buttons",
    labelnames=["channel_id", "reformat_type"]
)
press_count = Counter(
    "feedbackbot_button_press_total",
    "Total number of feedback buttons pressed by the bot",
    labelnames=["channel_id", "option"]
)
logger = logging.getLogger(__name__)


class Channel:
    def __init__(
            self,
            channel_id: int,
            options: Union[List[str], List[List[str]]],
            feedback_group_id: int,
            delay_feedback: bool,
    ):
        self.channel_id = channel_id
        self.options = options
        self.feedback_group_id = feedback_group_id
        self.delay_feedback = False

    @property
    def buttons(self) -> Union[List[Button], List[List[Button]]]:
        if isinstance(self.options[0], list):
            return [
                [Button.inline(option, f"option:{option}") for option in row]
                for row in self.options
            ]
        return [
            Button.inline(option, f"option:{option}")
            for option in self.options
        ]

    def list_options(self) -> List[str]:
        if isinstance(self.options[0], list):
            return sum(self.options, [])
        return self.options

    @classmethod
    def from_json(cls, config: Dict):
        return cls(
            config["channel_id"],
            config["options"],
            config["feedback_group_id"],
            config.get("delay_feedback", False),
        )


class FeedbackBot:
    RAND_DELAY_MIN_SECONDS = 4 * 60 * 60
    RAND_DELAY_MAX_SECONDS = 12 * 60 * 60

    def __init__(self, client: TelegramClient, channels: List[Channel], prom_port: Optional[int] = None):
        self.client = client
        self.channels = channels
        self.channel_dict = {channel.channel_id: channel for channel in channels}
        self.prom_port = prom_port or 7066
        for chan in channels:
            for reformat_type in ["edit", "resend"]:
                latest_msg.labels(channel_id=chan.channel_id, reformat_type=reformat_type)
                msg_count.labels(channel_id=chan.channel_id, reformat_type=reformat_type)
            for option in chan.list_options():
                latest_press.labels(channel_id=chan.channel_id, option=option)
                press_count.labels(channel_id=chan.channel_id, option=option)

    async def handle_new_message(self, event: events.NewMessage.Event) -> None:
        channel = self.channel_dict.get(event.chat_id)
        if not channel:
            return
        latest_msg.labels(channel_id=event.chat_id, reformat_type="edit").set_to_current_time()
        msg_count.labels(channel_id=event.chat_id, reformat_type="edit").inc()
        logger.info("Editing message")
        await self.client.edit_message(
            event.chat,
            event.message,
            buttons=channel.buttons
        )

    async def handle_forwarded_message(self, event: events.NewMessage.Event) -> None:
        channel = self.channel_dict.get(event.chat_id)
        if not channel:
            return
        latest_msg.labels(channel_id=event.chat_id, reformat_type="resend").set_to_current_time()
        msg_count.labels(channel_id=event.chat_id, reformat_type="resend").inc()
        logger.info("Resending message")
        await self.client.send_message(
            event.chat,
            event.message,
            buttons=channel.buttons
        )
        await self.client.delete_messages(event.chat, [event.message.id])

    async def handle_callback_button(self, event: events.CallbackQuery.Event) -> None:
        if not event.data.startswith(b"option:"):
            return
        channel = self.channel_dict.get(event.chat_id)
        if not channel:
            return
        user = event.sender
        user_name = " ".join(filter(None, [user.first_name, user.last_name]))
        option = event.data.decode().split(":", 1)[1]
        latest_press.labels(channel_id=event.chat_id, option=option).set_to_current_time()
        press_count.labels(channel_id=event.chat_id, option=option).inc()
        logger.info(f"Button press received: {option}")
        schedule_time = None
        schedule_time_fwd = None
        if channel.delay_feedback:
            random_delay_seconds = random.randrange(self.RAND_DELAY_MIN_SECONDS, self.RAND_DELAY_MAX_SECONDS)
            random_delay = datetime.timedelta(seconds=random_delay_seconds)
            schedule_time = datetime.datetime.now(datetime.timezone.utc) + random_delay
            schedule_time_fwd = schedule_time + datetime.timedelta(seconds=10)
        await self.client.send_message(
            channel.feedback_group_id, f"User [{user_name}](tg://user?id=user.id) has sent feedback: {option}",
            parse_mode="markdown",
            schedule=schedule_time,
        )
        await self.client.forward_messages(
            channel.feedback_group_id, event.message_id, event.chat_id, schedule=schedule_time_fwd,
        )

    def start(self) -> None:
        start_time.set_to_current_time()
        channel_ids = list(self.channel_dict.keys())
        self.client.add_event_handler(
            self.handle_new_message,
            events.NewMessage(chats=channel_ids, forwards=False)
        )
        self.client.add_event_handler(
            self.handle_forwarded_message,
            events.NewMessage(chats=channel_ids, forwards=True)
        )
        self.client.add_event_handler(
            self.handle_callback_button,
            events.CallbackQuery(pattern="^option:")
        )
        start_http_server(self.prom_port)
        logger.info("Handlers registered, running")
        self.client.run_until_disconnected()

    @classmethod
    def from_config(cls, config: Dict) -> 'FeedbackBot':
        client = TelegramClient(
            "feedback_bot",
            config["api_id"],
            config["api_hash"]
        )
        client.start(bot_token=config["bot_token"])
        channels = [Channel.from_json(c) for c in config["channels"]]
        prom_port = config.get("prom_port", 7066)
        return cls(client, channels, prom_port)
