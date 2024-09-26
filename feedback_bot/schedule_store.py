import asyncio
import json
import logging
from abc import ABC, abstractmethod
import datetime

from prometheus_client import Gauge
from telethon import TelegramClient
import dateutil.parser

logger = logging.getLogger(__name__)


schedule_store_size = Gauge(
    "feedbackbot_schedule_store_post_count",
    "Number of posts in the post schedule store",
)
latest_check_time = Gauge(
    "feedbackbot_schedule_store_latest_check_unixtime",
    "Unix timestamp of the last time the schedule store checked for scheduled messages",
)


class ScheduledPost(ABC):
    def __init__(self, feedback_group_id: int, schedule_time: datetime.datetime) -> None:
        self.feedback_group_id = feedback_group_id
        self.schedule_time: datetime.datetime = schedule_time

    @abstractmethod
    def to_json(self) -> dict:
        raise NotImplementedError()

    @classmethod
    def from_json(cls, data: dict) -> "ScheduledPost":
        if "fwd_msg_id" in data:
            return ScheduledForward.from_json(data)
        return ScheduledMessage.from_json(data)

    @abstractmethod
    async def send_message(self, client: TelegramClient) -> None:
        raise NotImplementedError()


class ScheduledMessage(ScheduledPost):

    def __init__(
            self,
            feedback_group_id: int,
            schedule_time: datetime.datetime,
            username: str,
            user_id: int,
            option: str,
    ) -> None:
        super().__init__(feedback_group_id, schedule_time)
        self.username = username
        self.user_id = user_id
        self.option = option

    def to_json(self) -> dict:
        return {
            "feedback_group_id": self.feedback_group_id,
            "schedule_time": self.schedule_time.isoformat(),
            "username": self.username,
            "user_id": self.user_id,
            "option": self.option,
        }

    @classmethod
    def from_json(cls, data: dict) -> "ScheduledMessage":
        return cls(
            data["feedback_group_id"],
            dateutil.parser.parse(data["schedule_time"]),
            data["username"],
            data["user_id"],
            data["option"],
        )

    async def send_message(self, client: TelegramClient) -> None:
        await client.send_message(
            self.feedback_group_id,
            f"User [{self.username}](tg://user?id={self.user_id}) has sent feedback: {self.option}",
            parse_mode="markdown",
        )


class ScheduledForward(ScheduledPost):

    def __init__(
            self,
            feedback_group_id: int,
            schedule_time: datetime.datetime,
            fwd_msg_id: int,
            fwd_chat_id: int,
    ) -> None:
        super().__init__(feedback_group_id, schedule_time)
        self.fwd_msg_id = fwd_msg_id
        self.fwd_chat_id = fwd_chat_id

    def to_json(self) -> dict:
        return {
            "feedback_group_id": self.feedback_group_id,
            "schedule_time": self.schedule_time.isoformat(),
            "fwd_msg_id": self.fwd_msg_id,
            "fwd_chat_id": self.fwd_chat_id,
        }

    @classmethod
    def from_json(cls, data: dict) -> "ScheduledForward":
        return cls(
            data["feedback_group_id"],
            dateutil.parser.parse(data["schedule_time"]),
            data["fwd_msg_id"],
            data["fwd_chat_id"],
        )

    async def send_message(self, client: TelegramClient) -> None:
        await client.forward_messages(
            self.feedback_group_id, self.fwd_msg_id, self.fwd_chat_id,
        )


class ScheduleStore:
    FILENAME = "schedule_store.json"
    WAIT_BEFORE_CHECK_SECONDS = 60 * 5

    def __init__(self, scheduled_posts: list[ScheduledPost], client: TelegramClient) -> None:
        self.scheduled_posts: list[ScheduledPost] = scheduled_posts
        self.client = client
        self.running = False
        schedule_store_size.set_function(lambda: len(self.scheduled_posts))

    @classmethod
    def load_from_json(cls, client: TelegramClient) -> "ScheduleStore":
        try:
            with open(cls.FILENAME, "r") as f:
                raw_data = json.load(f)
        except FileNotFoundError:
            return cls([], client)
        scheduled_posts = [ScheduledPost.from_json(data) for data in raw_data["scheduled_posts"]]
        return cls(scheduled_posts, client)

    def save_to_json(self) -> None:
        raw_data = {
            "scheduled_posts": [post.to_json() for post in self.scheduled_posts]
        }
        with open(self.FILENAME, "w") as f:
            json.dump(raw_data, f, indent=2)

    def schedule(self, post: ScheduledPost) -> None:
        self.scheduled_posts.append(post)
        self.save_to_json()

    async def send_all(self) -> None:
        logger.info("Checking for new scheduled posts to send")
        latest_check_time.set_to_current_time()
        now = datetime.datetime.now(datetime.timezone.utc)
        for post in self.scheduled_posts[:]:
            if post.schedule_time < now:
                await post.send_message(self.client)
                self.scheduled_posts.remove(post)

    async def run(self) -> None:
        self.running = True
        logger.info("Starting schedule store watcher")
        while self.running:
            try:
                await self.send_all()
            except Exception as e:
                logger.warning("Failed to send all scheduled posts", exc_info=e)
            await asyncio.sleep(self.WAIT_BEFORE_CHECK_SECONDS)
        logger.info("Schedule store shutting down")

    def stop(self) -> None:
        self.running = False
