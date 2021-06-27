from typing import List, Dict, Union

from telethon import events, TelegramClient, Button


class Channel:
    def __init__(self, channel_id: int, options: List[str], feedback_group_id: int):
        self.channel_id = channel_id
        self.options = options
        self.feedback_group_id = feedback_group_id

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

    @classmethod
    def from_json(cls, config: Dict):
        return cls(config["channel_id"], config["options"], config["feedback_group_id"])


class FeedbackBot:
    def __init__(self, client: TelegramClient, channels: List[Channel]):
        self.client = client
        self.channels = channels
        self.channel_dict = {channel.channel_id: channel for channel in channels}

    async def handle_new_message(self, event: events.NewMessage.Event) -> None:
        channel = self.channel_dict.get(event.chat_id)
        if not channel:
            return
        await self.client.edit_message(
            event.chat,
            event.message,
            buttons=channel.buttons
        )

    async def handle_forwarded_message(self, event: events.NewMessage.Event) -> None:
        channel = self.channel_dict.get(event.chat_id)
        if not channel:
            return
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
        await self.client.send_message(
            channel.feedback_group_id, f"User [{user_name}](tg://user?id=user.id) has sent feedback: {option}",
            parse_mode="markdown"
        )
        await self.client.forward_messages(
            channel.feedback_group_id, event.message_id, event.chat_id
        )

    def start(self) -> None:
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
        return cls(client, channels)
