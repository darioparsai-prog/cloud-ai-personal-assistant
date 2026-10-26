"""Suivi de colis (17TRACK)."""
import asyncio
import logging

from telegram.ext import CommandHandler

from colis_agent import actualiser_colis, ajouter_colis, formater_changement, formater_colis, supprimer_colis
from config import INTERVALLE_COLIS_S
from security import texte_erreur
from utils import envoyer, esc_md, repondre

log = logging.getLogger(__name__)


def _statut(item):
    return (
        f"📦 **{esc_md(item.get('nom') or 'Colis')}**\n"
        f"🔖 {esc_md(item.get('numero', '?'))}\n"
        f"📍 Statut : {esc_md(item.get('subtag') or item.get('tag') or 'Inconnu')}"
    )


async def colis(update, context):
    msg, chat_id, args = update.message, update.effective_chat.id, list(context.args)

    if not args:
        await repondre(msg, formater_colis(chat_id), disable_web_page_preview=True)
        return

    if args[0].lower() == "supprimer":
        if len(args) < 2 or not args[1].isdigit():
            await repondre(msg, "❌ Format : `/colis supprimer ID`")
            return
        ok = await asyncio.to_thread(supprimer_colis, int(args[1]), chat_id)  # appelle 17TRACK
        await repondre(msg, f"🗑️ Colis **#{args[1]}** supprimé." if ok else "❌ Colis introuvable.")
        return

    if args[0].lower() == "ajouter":
        args = args[1:]
        if not args:
            await repondre(msg, "❌ Format : `/colis ajouter TRACKING [nom]`")
            return

    numero, nom = args[0], " ".join(args[1:]).strip() or None
    await repondre(msg, "📦 J'ajoute le colis et je demande son premier statut...")
    try:
        item, nouveau = await asyncio.to_thread(ajouter_colis, chat_id, numero, nom)
    except Exception as exc:
        await repondre(msg, f"❌ Impossible d'ajouter le colis.\n\n_{esc_md(texte_erreur(exc, 'colis'))}_")
        return
    prefixe = "✅ **Colis ajouté !**" if nouveau else "ℹ️ Ce numéro de suivi est déjà enregistré."
    await repondre(msg, f"{prefixe}\n\n{_statut(item)}", disable_web_page_preview=True)


async def verifier_colis_automatique(context):
    try:
        changements = await asyncio.to_thread(actualiser_colis)
    except Exception:
        log.exception("Vérification des colis impossible")
        return
    # actualiser_colis() renvoie des tuples (colis, suivi)
    for colis_maj, suivi in changements:
        try:
            await envoyer(
                context.bot, int(colis_maj["chat_id"]), formater_changement(colis_maj, suivi),
                disable_web_page_preview=True,
            )
        except Exception:
            log.exception("Notification colis impossible")


def register(app):
    app.add_handler(CommandHandler("colis", colis))
    app.job_queue.run_repeating(verifier_colis_automatique, interval=INTERVALLE_COLIS_S, first=60)
    return [("colis", "Ajouter ou suivre mes colis")]
