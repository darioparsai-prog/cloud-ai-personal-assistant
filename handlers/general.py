"""Commandes de base."""
from telegram.ext import CommandHandler

from utils import repondre


async def start(update, context):
    await repondre(update.message, "🤖 Bonjour ! Ton assistant personnel est opérationnel !")


async def bonjour(update, context):
    await repondre(update.message, "👋 Bonjour ! Je suis ton assistant personnel.")


async def test(update, context):
    await repondre(update.message, "✅ Tout fonctionne correctement !")


def register(app):
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("bonjour", bonjour))
    app.add_handler(CommandHandler("test", test))
    return [("start", "Démarrer l'assistant")]
