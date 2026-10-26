"""Billets et réservations : PDF ou photo reçus → extraction → enregistrement."""
import asyncio
import os
import tempfile
from pathlib import Path

from telegram.ext import CommandHandler, MessageHandler, filters

from billet_agent import analyser_document, enregistrer_billet, formater_billets, supprimer_billet
from config import TAILLE_MAX_FICHIER
from security import texte_erreur
from utils import esc_md, repondre


def _confirmation(billet):
    lignes = ["🎟️ **Billet enregistré !**", ""]
    if billet.get("titre"):
        lignes.append(f"📌 {esc_md(billet['titre'])}")
    if billet.get("type"):
        lignes.append(f"📂 Type : {esc_md(billet['type'])}")
    if billet.get("compagnie"):
        lignes.append(f"🏢 {esc_md(billet['compagnie'])}")
    if billet.get("date"):
        lignes.append(f"📅 {billet['date']}")
    if billet.get("heure"):
        lignes.append(f"🕐 {billet['heure']}")
    if billet.get("lieu"):
        lignes.append(f"📍 {esc_md(billet['lieu'])}")
    if billet.get("depart") or billet.get("destination"):
        lignes.append("🛫 " + " → ".join(esc_md(x) for x in (billet.get("depart"), billet.get("destination")) if x))
    if billet.get("reference"):
        lignes.append(f"🔖 Référence : {esc_md(billet['reference'])}")
    lignes.append(f"\nID : **{billet['id']}**")
    return "\n".join(lignes)


async def _traiter(update, fichier_telegram, nom, attente, echec):
    """Télécharge dans un fichier temporaire, analyse (thread), enregistre, nettoie."""
    if fichier_telegram.file_size and fichier_telegram.file_size > TAILLE_MAX_FICHIER:
        await repondre(update.message, f"❌ Fichier trop volumineux (max {TAILLE_MAX_FICHIER // 1024 // 1024} Mo).")
        return
    await repondre(update.message, attente)

    fd, chemin = tempfile.mkstemp(suffix=Path(nom).suffix.lower() or ".bin")
    os.close(fd)
    chemin = Path(chemin)
    try:
        tg_file = await fichier_telegram.get_file()
        await tg_file.download_to_drive(custom_path=chemin)
        analyse = await asyncio.to_thread(analyser_document, chemin, nom)
        billet = await asyncio.to_thread(enregistrer_billet, update.effective_chat.id, analyse, chemin, nom)
        await repondre(update.message, _confirmation(billet))
    except Exception as exc:
        await repondre(update.message, f"❌ {echec}\n\n_{esc_md(texte_erreur(exc, 'billet'))}_")
    finally:
        chemin.unlink(missing_ok=True)


async def recevoir_document(update, context):
    doc = update.message.document
    nom = doc.file_name or "billet.pdf"
    mime = (doc.mime_type or "").lower()
    if not (nom.lower().endswith(".pdf") or mime == "application/pdf" or mime.startswith("image/")):
        return
    await _traiter(update, doc, nom, "🎟️ Je lis ton billet/réservation...", "Je n'ai pas réussi à analyser ce billet.")


async def recevoir_photo(update, context):
    photo = update.message.photo[-1]
    await _traiter(update, photo, "billet.jpg", "🎟️ Je lis la photo de ton billet...", "Je n'ai pas réussi à lire cette photo.")


async def billets(update, context):
    await repondre(update.message, formater_billets(update.effective_chat.id), disable_web_page_preview=True)


async def annuler_billet(update, context):
    if not context.args or not context.args[0].isdigit():
        await repondre(update.message, "❌ Format : `/annuler_billet ID`\n\nUtilise /billets pour voir les IDs.")
        return
    billet_id = int(context.args[0])
    if supprimer_billet(billet_id, update.effective_chat.id):
        await repondre(update.message, f"🗑️ Billet **#{billet_id}** supprimé.")
    else:
        await repondre(update.message, "❌ Billet introuvable.")


def register(app):
    app.add_handler(MessageHandler(filters.Document.ALL, recevoir_document))
    app.add_handler(MessageHandler(filters.PHOTO, recevoir_photo))
    app.add_handler(CommandHandler("billets", billets))
    app.add_handler(CommandHandler("annuler_billet", annuler_billet))
    return [
        ("billets", "Voir mes billets et réservations"),
        ("annuler_billet", "Supprimer un billet"),
    ]
