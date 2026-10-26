"""Facturation mensuelle : question en fin de mois, réponse libre en heures, PDF."""
import asyncio
import logging
import math
import re
from datetime import timedelta

from telegram.ext import ApplicationHandlerStop, CommandHandler, MessageHandler, filters

from config import HEURE_FACTURE, OWNER_ID
from facture_agent import TAUX_HORAIRE, creer_facture, marquer_mois_en_attente, mois_en_attente, mois_francais
from security import texte_erreur
from utils import envoyer, maintenant, repondre

log = logging.getLogger(__name__)
HEURES_MAX = 744  # 31 jours × 24 h : au-delà, c'est forcément une faute de frappe


def convertir_heures(texte: str) -> float:
    """'12' · '12,5' · '12h' · '12h30' · '12:30' · '12 heures' → nombre d'heures."""
    v = texte.strip().lower().replace(" ", "").replace("heures", "h").replace("heure", "h")
    m = re.fullmatch(r"(\d+)[h:](\d{1,2})?", v)
    if m:
        return int(m[1]) + int(m[2] or 0) / 60
    return float(v.replace(",", "."))


async def demander_facture_fin_de_mois(context):
    aujourdhui = maintenant().date()
    if (aujourdhui + timedelta(days=1)).month == aujourdhui.month:
        return  # pas le dernier jour du mois
    mois = f"{aujourdhui.year:04d}-{aujourdhui.month:02d}"
    if mois_en_attente() == mois:
        return
    marquer_mois_en_attente(aujourdhui.year, aujourdhui.month)
    await envoyer(
        context.bot, OWNER_ID,
        f"🧾 **Fin du mois !**\n\nCombien d'heures de cours particuliers as-tu travaillé en "
        f"{mois_francais(aujourdhui.month)} ?\n\nRéponds simplement avec le nombre d'heures "
        "(ex : `12`, `12,5` ou `12h30`).",
    )


async def reponse_facture(update, context):
    attente = mois_en_attente()
    if not attente:
        return  # texte libre sans facture en attente : on ignore

    try:
        heures = convertir_heures(update.message.text)
        if not (math.isfinite(heures) and 0 < heures <= HEURES_MAX):
            raise ValueError
    except (ValueError, TypeError):
        if re.match(r"^\s*\d", update.message.text or ""):  # ressemble à un nombre d'heures mal écrit
            await repondre(update.message, "❌ Je n'ai pas compris le nombre d'heures. Réponds par exemple `12`, `12,5` ou `12h30`.")
            raise ApplicationHandlerStop
        return  # autre chose : on laisse l'assistant IA (groupe suivant) répondre

    annee, mois = map(int, attente.split("-"))
    try:
        chemin = await asyncio.to_thread(creer_facture, heures, annee, mois)
    except Exception as exc:
        texte_erreur(exc, "facture")  # journalisé
        await repondre(update.message, "❌ Impossible de créer la facture pour le moment.")
        raise ApplicationHandlerStop

    await repondre(update.message, f"✅ Facture créée pour {heures:g} h, soit **{heures * TAUX_HORAIRE:.2f} €**.")
    numero = chemin.stem.rsplit("_", 1)[-1]  # ex. 2026-003
    with open(chemin, "rb") as f:
        await update.message.reply_document(document=f, filename=chemin.name, caption=f"🧾 Facture {numero}")
    raise ApplicationHandlerStop  # réponse traitée : l'assistant IA ne doit pas la recevoir


async def test_facture(update, context):
    if mois_en_attente() is None:
        aujourdhui = maintenant().date()
        marquer_mois_en_attente(aujourdhui.year, aujourdhui.month)
    await repondre(update.message, "🧪 Test facture : combien d'heures veux-tu facturer ? Réponds avec le nombre.")


def register(app):
    app.add_handler(CommandHandler("test_facture", test_facture))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, reponse_facture))
    app.job_queue.run_daily(demander_facture_fin_de_mois, time=HEURE_FACTURE)
    return [("test_facture", "Tester la demande de facture mensuelle")]
