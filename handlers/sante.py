"""Rappel santé (Olumiant) : question à 11h, relance toutes les heures jusqu'à confirmation."""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackQueryHandler, CommandHandler

from config import HEURE_SANTE, OWNER_ID, RELANCE_SANTE_HEURE_MAX, RELANCE_SANTE_S
from utils import envoyer, maintenant

JOB_RELANCE = "relance_olumiant"


def _arreter_relances(job_queue):
    for job in job_queue.get_jobs_by_name(JOB_RELANCE):
        job.schedule_removal()


async def _poser_la_question(context):
    clavier = InlineKeyboardMarkup([[
        InlineKeyboardButton("Oui ✅", callback_data="olumiant_oui"),
        InlineKeyboardButton("Non ⏳", callback_data="olumiant_non"),
    ]])
    await envoyer(context.bot, OWNER_ID, "💊 **Rappel santé**\n\nAs-tu pris Olumiant ?", reply_markup=clavier)


async def _relance(context):
    if maintenant().hour >= RELANCE_SANTE_HEURE_MAX:   # pas de relance en pleine nuit
        _arreter_relances(context.job_queue)
        return
    await _poser_la_question(context)


async def rappel_initial(context):
    _arreter_relances(context.job_queue)
    await _poser_la_question(context)
    context.job_queue.run_repeating(_relance, interval=RELANCE_SANTE_S, first=RELANCE_SANTE_S, name=JOB_RELANCE)


async def cmd_test_olumiant(update, context):
    await _poser_la_question(context)


async def bouton_olumiant(update, context):
    query = update.callback_query
    await query.answer()
    if query.data == "olumiant_oui":
        _arreter_relances(context.job_queue)
        await query.edit_message_text("✅ C'est noté ! Olumiant pris. Prochain rappel demain à 11 h.")
    elif query.data == "olumiant_non":
        await query.edit_message_text("⏳ Entendu. Je te redemanderai dans 1 heure.")


def register(app):
    app.add_handler(CommandHandler("test_olumiant", cmd_test_olumiant))
    app.add_handler(CallbackQueryHandler(bouton_olumiant, pattern=r"^olumiant_"))
    app.job_queue.run_daily(rappel_initial, time=HEURE_SANTE)
    return []
