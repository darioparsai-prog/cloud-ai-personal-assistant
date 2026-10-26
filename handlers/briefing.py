"""Briefing du matin et alertes d'examens."""
import asyncio
import logging
from datetime import datetime

from telegram.ext import CommandHandler

from config import HEURE_BRIEFING, HEURE_EXAMENS, OWNER_ID, TZ
from examens_agent import afficher_alertes_examens
from calendar_agent import afficher_cours_du_jour
from rappel_agent import obtenir_rappels
from todoist_agent import afficher_taches_aujourd_hui
from utils import appel_securise, envoyer, esc_md, maintenant, repondre, ville_du_jour
from weather import obtenir_meteo

log = logging.getLogger(__name__)
SEPARATEUR = "━━━━━━━━━━━━━━━"


def _rappels_du_jour():
    aujourdhui = maintenant().date()
    lignes = []
    for r in obtenir_rappels(OWNER_ID):
        dt = datetime.fromisoformat(r["datetime"]).astimezone(TZ)
        if dt.date() == aujourdhui:
            lignes.append(f"• {dt:%H:%M} — {esc_md(r['texte'])}")
    return "🔔 **Rappels du jour**\n\n" + "\n".join(lignes) if lignes else None


async def briefing_matin(context):
    # Les 3 sources sont interrogées EN PARALLÈLE, chacune dans un thread.
    meteo, cours, taches = await asyncio.gather(
        appel_securise(obtenir_meteo, "❌ Météo indisponible.", ville_du_jour()),
        appel_securise(afficher_cours_du_jour, "❌ Planning indisponible."),
        appel_securise(afficher_taches_aujourd_hui, "❌ Tâches indisponibles."),
    )
    sections = [meteo, cours, taches]
    rappels = _rappels_du_jour()
    if rappels:
        sections.append(rappels)
    texte = "☀️ **Bonjour monsieur !**\n\n" + f"\n\n{SEPARATEUR}\n\n".join(sections)
    await envoyer(context.bot, OWNER_ID, texte)


async def alertes_examens_matin(context):
    message = await appel_securise(afficher_alertes_examens, None)
    if message:
        await envoyer(context.bot, OWNER_ID, message)


async def cmd_briefing(update, context):
    await briefing_matin(context)


async def cmd_test_examens(update, context):
    message = await appel_securise(afficher_alertes_examens, None)
    await repondre(update.message, message or "ℹ️ Aucune alerte d'examen aujourd'hui.")


def register(app):
    app.add_handler(CommandHandler("briefing", cmd_briefing))
    app.add_handler(CommandHandler("test_examens", cmd_test_examens))
    app.job_queue.run_daily(briefing_matin, time=HEURE_BRIEFING)
    app.job_queue.run_daily(alertes_examens_matin, time=HEURE_EXAMENS)
    return [
        ("briefing", "Recevoir le briefing du matin tout de suite"),
        ("test_examens", "Tester les alertes d'examens"),
    ]
