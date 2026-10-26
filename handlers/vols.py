"""Recherche et suivi de prix des vols (SerpApi / Google Flights)."""
import asyncio
import logging
import re
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CommandHandler

from config import INTERVALLE_VOLS_S
from flight_agent import (
    actualiser_suivi,
    ajouter_suivi,
    format_results,
    formater_suivis,
    google_flights_url,
    message_alerte,
    message_suivi,
    obtenir_suivis,
    rechercher_vols,
    sauvegarder_suivi,
    supprimer_suivi,
)
from security import cooldown, texte_erreur
from utils import envoyer, esc_md, repondre

log = logging.getLogger(__name__)


def _date_vol(valeur):
    """Accepte YYYY-MM-DD ou DD/MM/YYYY."""
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(valeur, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return None


_RE_OPTION = re.compile(r"^(escales?|duree|durée|temps)[=:](.+)$", re.IGNORECASE)


def _duree_minutes(valeur):
    """'15h' · '15h30' · '15' (heures) → minutes."""
    m = re.fullmatch(r"(\d{1,2})(?:h(\d{1,2})?)?", valeur.lower().replace(" ", ""))
    if not m:
        raise ValueError("Durée non comprise. Exemples : duree=15h ou duree=15h30")
    minutes = int(m[1]) * 60 + int(m[2] or 0)
    if not 60 <= minutes <= 48 * 60:
        raise ValueError("Durée maximum : entre 1h et 48h.")
    return minutes


def _extraire_options(args):
    """Sépare les options des autres mots → (mots restants, max_escales, max_duree)."""
    restants, max_escales, max_duree = [], None, None
    for arg in args:
        if arg.lower() == "direct":
            max_escales = 0
            continue
        m = _RE_OPTION.match(arg)
        if not m:
            restants.append(arg)
            continue
        if m[1].lower().startswith("escale"):
            if not m[2].isdigit() or int(m[2]) > 2:
                raise ValueError("Escales : 0, 1 ou 2 (ex : escales=1).")
            max_escales = int(m[2])
        else:
            max_duree = _duree_minutes(m[2])
    return restants, max_escales, max_duree


def _arguments_vol(args):
    """/vol destination date [date_retour] [direct | escales=N] [duree=15h]
    → (destination, aller, retour|None, max_escales|None, max_duree|None) ou None.
    Lève ValueError (message affichable) si une option est invalide."""
    args, max_escales, max_duree = _extraire_options(args)
    dates, mots = [], []
    for arg in args:
        (dates if _date_vol(arg) else mots).append(_date_vol(arg) or arg)
    if not mots or not dates or len(dates) > 2:
        return None
    return " ".join(mots), dates[0], dates[1] if len(dates) == 2 else None, max_escales, max_duree


def _usage(commande):
    return (
        f"❌ Format : /{commande} destination date [date_retour] [direct | escales=N] [duree=15h]\n\n"
        f"Exemples :\n"
        f"/{commande} Bangkok 28/12/2026 18/01/2027\n"
        f"/{commande} Bangkok 28/12/2026 18/01/2027 escales=1\n"
        f"/{commande} Tokyo 10/01/2027 duree=16h\n"
        f"/{commande} Rome 05/12/2026 direct"
    )


def _clavier_google_flights(url):
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔎 Voir sur Google Flights", url=url)]])


@cooldown(10)
async def vol(update, context):
    try:
        parsed = _arguments_vol(context.args)
    except ValueError as exc:
        await repondre(update.message, f"❌ {exc}", parse_mode=None)
        return
    if not parsed:
        await repondre(update.message, _usage("vol"), parse_mode=None)
        return

    destination, aller, retour, max_escales, max_duree = parsed
    await repondre(update.message, "🔎 Recherche des vols depuis Paris...")
    try:
        data, nom, _ = await asyncio.to_thread(
            rechercher_vols, destination, aller, retour, max_escales=max_escales, max_duree=max_duree,
        )
        texte, _ = format_results(data, nom, aller, retour, max_escales=max_escales, max_duree=max_duree)
        clavier = _clavier_google_flights(google_flights_url(nom, aller, retour, data))
        await repondre(update.message, texte, reply_markup=clavier)
    except Exception as exc:
        await repondre(update.message, f"❌ Erreur recherche vols : {esc_md(texte_erreur(exc, 'vol'))}")


@cooldown(10)
async def vol_suivre(update, context):
    try:
        parsed = _arguments_vol(context.args)
    except ValueError as exc:
        await repondre(update.message, f"❌ {exc}", parse_mode=None)
        return
    if not parsed:
        await repondre(update.message, _usage("vol_suivre"), parse_mode=None)
        return

    destination, aller, retour, max_escales, max_duree = parsed
    await repondre(update.message, "🔎 Création du suivi et première analyse...")
    try:
        data, nom, arrival_id = await asyncio.to_thread(
            rechercher_vols, destination, aller, retour, max_escales=max_escales, max_duree=max_duree,
        )
        _, resultats = format_results(data, nom, aller, retour)
        if not resultats:
            await repondre(update.message, "❌ Aucun vol trouvé, suivi non créé.")
            return
        prix = min(float(x["price"]) for x in resultats)
        suivi = ajouter_suivi(
            update.effective_chat.id, nom, aller, retour, arrival_id=arrival_id, price=prix,
            max_escales=max_escales, max_duree=max_duree,
        )
        clavier = _clavier_google_flights(google_flights_url(nom, aller, retour, data))
        await repondre(update.message, message_suivi(suivi), reply_markup=clavier)
    except Exception as exc:
        await repondre(update.message, f"❌ Erreur création du suivi : {esc_md(texte_erreur(exc, 'vol_suivre'))}")


async def vols_suivis(update, context):
    suivis = obtenir_suivis(update.effective_chat.id)
    if not suivis:
        await repondre(update.message, "✈️ Aucun suivi de vol actif.")
        return
    await repondre(update.message, formater_suivis(suivis))


async def annuler_vol(update, context):
    if not context.args:
        await repondre(update.message, "❌ Indique l'ID du suivi. Utilise /vols_suivis pour le voir.", parse_mode=None)
        return
    chat_id, suivi_id = update.effective_chat.id, context.args[0]
    if not any(x.get("id") == suivi_id for x in obtenir_suivis(chat_id)):
        await repondre(update.message, "❌ Suivi introuvable.")
        return
    supprimer_suivi(chat_id, suivi_id)
    await repondre(update.message, "🛑 Suivi de vol supprimé.")


async def verifier_vols_automatique(context):
    for chat_id, suivi in obtenir_suivis():
        try:
            analyse = await asyncio.to_thread(actualiser_suivi, suivi)
            if analyse is None:
                continue
            sauvegarder_suivi(chat_id, suivi)
            alerte = message_alerte(suivi, analyse)
            if alerte:
                await envoyer(context.bot, int(chat_id), alerte, reply_markup=_clavier_google_flights(analyse["url"]))
        except Exception:
            log.exception("Erreur suivi vol %s", suivi.get("id"))


def register(app):
    app.add_handler(CommandHandler("vol", vol))
    app.add_handler(CommandHandler("vol_suivre", vol_suivre))
    app.add_handler(CommandHandler("vols_suivis", vols_suivis))
    app.add_handler(CommandHandler("annuler_vol", annuler_vol))
    app.job_queue.run_repeating(verifier_vols_automatique, interval=INTERVALLE_VOLS_S, first=300)
    return [
        ("vol", "Rechercher des vols depuis Paris"),
        ("vol_suivre", "Suivre le prix d'un vol"),
        ("vols_suivis", "Voir mes suivis de vols"),
        ("annuler_vol", "Arrêter un suivi de vol"),
    ]
