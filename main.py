# This is a sample Python script.

# Press Shift+F10 to execute it or replace it with your code.
# Press Double Shift to search everywhere for classes, files, tool windows, actions, and settings.
import json

from feedback_bot.feedback_bot import FeedbackBot


if __name__ == '__main__':
    with open("config.json", "r") as f:
        config = json.load(f)
    bot = FeedbackBot.from_config(config)
    bot.start()
