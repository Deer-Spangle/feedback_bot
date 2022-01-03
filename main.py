# This is a sample Python script.

# Press Shift+F10 to execute it or replace it with your code.
# Press Double Shift to search everywhere for classes, files, tool windows, actions, and settings.
import json
import logging
import sys

from feedback_bot.feedback_bot import FeedbackBot


def setup_logging() -> None:
    formatter = logging.Formatter("{asctime}:{levelname}:{name}:{message}", style="{")
    base_logger = logging.getLogger()
    base_logger.setLevel(logging.INFO)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    base_logger.addHandler(console_handler)


if __name__ == '__main__':
    setup_logging()
    with open("config.json", "r") as f:
        config = json.load(f)
    bot = FeedbackBot.from_config(config)
    bot.start()
