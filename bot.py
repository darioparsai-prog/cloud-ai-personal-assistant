"""Point d'entrée : construit l'application et branche les modules.

Lancer :  python bot.py
Chaque module de `handlers/` expose register(app) qui ajoute ses handlers / jobs
et renvoie ses entrées pour le menu Telegram.
"""
import logging

import horloge

horloge.forcer_fuseau_processus()  # heure de Paris même sur une VM en UTC (Linux)

from telegram import BotCommand
from telegram.error import NetworkError
from telegram.ext import Application
from telegram.request import HTTPXRequest

from config import OWNER_ID, TOKEN
from handlers import billets, briefing, colis, facture, general, llm, rappels, sante, simple, travel, vols
from security import configurer_logs, installer_garde

log = logging.getLogger("bot")

MODULES = [general, briefing, simple, travel, rappels, sante, facture, billets, colis, vols, llm]


async def post_init(app):
    await app.bot.set_my_commands([BotCommand(c, d) for c, d in app.bot_data["menu"]])
    rappels.restaurer_rappels(app)   # reprogramme les rappels sauvegardés


async def erreur_globale(update, context):
    if isinstance(context.error, NetworkError):   # coupure réseau / timeout : transitoire
        log.warning("Erreur réseau : %s", context.error)
        return
    log.error("Exception non gérée", exc_info=context.error)
    try:  # uniquement le type d'erreur : jamais le détail (peut contenir des secrets)
        await context.bot.send_message(OWNER_ID, f"⚠️ Erreur interne : {type(context.error).__name__} (voir bot.log)")
    except Exception:
        pass


def construire_application() -> Application:
    request = HTTPXRequest(connect_timeout=30.0, read_timeout=30.0, write_timeout=30.0, pool_timeout=30.0)
    app = Application.builder().token(TOKEN).request(request).post_init(post_init).build()

    installer_garde(app)                 # group=-1 : passe avant tout le reste
    menu = []
    for module in MODULES:
        menu.extend(module.register(app))
    app.bot_data["menu"] = menu
    app.add_error_handler(erreur_globale)
    return app


if __name__ == "__main__":
    configurer_logs()
    log.info("🤖 Bot démarré")
    construire_application().run_polling(drop_pending_updates=True)
