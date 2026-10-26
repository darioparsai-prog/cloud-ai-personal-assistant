"""Trajet, essence, parkings et réception de la position."""
import asyncio

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from telegram.ext import CallbackQueryHandler, CommandHandler, MessageHandler, filters

from essence_agent import RAYONS_DISPONIBLES, afficher_essence_sur_route, afficher_stations
from parking_agent import lien_waze, rechercher_parkings, rechercher_parkings_autour_destination
from route_agent import calculer_route, enregistrer_position, obtenir_position
from security import cooldown, texte_erreur
from travel_agent import obtenir_destination_par_defaut, preparer_message_trajet
from utils import esc_md, repondre

PAS_D_APERCU = {"disable_web_page_preview": True}


def _bouton_position():
    return ReplyKeyboardMarkup(
        [[KeyboardButton("📍 Envoyer ma position", request_location=True)]],
        resize_keyboard=True, one_time_keyboard=True,
    )


# ============================================================
# TRAJET
# ============================================================

async def trajet(update, context):
    destination = " ".join(context.args).strip()
    texte, clavier_waze = preparer_message_trajet(destination or None)
    context.user_data["derniere_destination"] = destination or obtenir_destination_par_defaut()

    boutons = list(clavier_waze.inline_keyboard) + [
        [InlineKeyboardButton("⛽ Trouver une station sur le trajet", callback_data="essence_trajet")],
        [InlineKeyboardButton("🅿️ Chercher un parking à destination", callback_data="parking_destination")],
    ]
    await repondre(update.message, texte, reply_markup=InlineKeyboardMarkup(boutons))


@cooldown(15)
async def bouton_essence_trajet(update, context):
    query = update.callback_query
    await query.answer()

    position = obtenir_position(update.effective_chat.id)
    destination = context.user_data.get("derniere_destination")

    if not position:
        await repondre(
            query.message,
            "📍 **J'ai besoin de ta position pour calculer le trajet.**\n\n"
            "Envoie-moi ta position depuis Telegram, puis relance `/trajet` "
            "et clique sur **⛽ Trouver une station sur le trajet**.",
        )
        return
    if not destination:
        await repondre(query.message, "❌ Je n'ai plus la destination de ton dernier trajet. Relance `/trajet destination`.")
        return

    await repondre(query.message, "⛽ Je calcule ton itinéraire et je cherche les meilleures stations sur le chemin...")
    try:
        route = await asyncio.to_thread(calculer_route, position[0], position[1], destination)
        message = await asyncio.to_thread(afficher_essence_sur_route, route, "e10")
    except Exception as exc:
        message = f"❌ **Impossible de chercher les stations sur le trajet.**\n\n_{esc_md(texte_erreur(exc, 'essence trajet'))}_"
    await repondre(query.message, message, **PAS_D_APERCU)


# ============================================================
# PARKINGS
# ============================================================

async def _par_destination(destination):
    return await asyncio.to_thread(rechercher_parkings_autour_destination, destination, rayon_km=3, limite=5)


async def _par_position(latitude, longitude):
    parkings = await asyncio.to_thread(rechercher_parkings, latitude, longitude, rayon_km=3, limite=5)
    return "ta position", parkings


async def _afficher_parkings(message, recherche):
    """`recherche` : coroutine qui renvoie (nom du lieu, liste de parkings)."""
    try:
        lieu, parkings = await recherche
    except Exception as exc:
        await repondre(message, f"❌ Impossible de rechercher les parkings pour le moment.\n\n_{esc_md(texte_erreur(exc, 'parking'))}_")
        return

    if not parkings:
        await repondre(message, f"🅿️ Aucun parking trouvé dans un rayon de 3 km autour de {esc_md(lieu)}.")
        return

    texte = f"🅿️ **Parkings à proximité**\n\n📍 {esc_md(lieu)}\n\n"
    boutons = []
    for index, p in enumerate(parkings, start=1):
        texte += f"**{index}. {esc_md(p['nom'])}** — {p['distance_km']:.1f} km\n"
        if p.get("capacite"):
            texte += f"   🅿️ Capacité : {esc_md(p['capacite'])}\n"
        if p.get("fee") == "yes":
            texte += "   💳 Payant\n"
        elif p.get("fee") == "no":
            texte += "   🆓 Gratuit\n"
        texte += "\n"
        nom_bouton = p["nom"] if len(p["nom"]) <= 35 else p["nom"][:32] + "..."
        boutons.append([InlineKeyboardButton(f"🧭 {index}. {nom_bouton}", url=lien_waze(p["latitude"], p["longitude"]))])

    texte += "Choisis un parking pour l'ouvrir directement dans Waze."
    await repondre(message, texte, reply_markup=InlineKeyboardMarkup(boutons), **PAS_D_APERCU)


async def parking(update, context):
    destination = " ".join(context.args).strip()
    if destination:
        await repondre(update.message, f"🅿️ Je cherche les parkings autour de **{esc_md(destination)}**...")
        await _afficher_parkings(update.message, _par_destination(destination))
        return

    position = obtenir_position(update.effective_chat.id)
    if not position:
        context.user_data["attente_parking"] = True
        await repondre(
            update.message,
            "🅿️ **Pour chercher les parkings autour de toi, j'ai besoin de ta position.**\n\nEnvoie-moi ta position ci-dessous.",
            reply_markup=_bouton_position(),
        )
        return

    await repondre(update.message, "🅿️ Je cherche les parkings autour de toi...")
    await _afficher_parkings(update.message, _par_position(*position))


async def bouton_parking_destination(update, context):
    query = update.callback_query
    await query.answer()
    destination = context.user_data.get("derniere_destination")
    if not destination:
        await repondre(query.message, "❌ Je n'ai plus la destination de ton dernier trajet. Relance `/trajet destination`.")
        return
    await repondre(query.message, f"🅿️ Je cherche les parkings autour de **{esc_md(destination)}**...")
    await _afficher_parkings(query.message, _par_destination(destination))


# ============================================================
# ESSENCE
# ============================================================

async def essence(update, context):
    context.user_data.pop("attente_essence", None)
    boutons = [InlineKeyboardButton(f"{r} km", callback_data=f"essence_rayon_{r}") for r in RAYONS_DISPONIBLES]
    await repondre(
        update.message,
        "⛽ **Choisis ton rayon**\n\nJe chercherai les meilleurs prix en 🇫🇷 France, 🇧🇪 Belgique et 🇱🇺 Luxembourg.",
        reply_markup=InlineKeyboardMarkup([boutons[:2], boutons[2:]]),
    )


async def bouton_essence_rayon(update, context):
    query = update.callback_query
    await query.answer()
    try:
        rayon = int(query.data.split("_")[-1])
    except ValueError:
        rayon = 50
    if rayon not in RAYONS_DISPONIBLES:
        rayon = 50

    context.user_data["attente_essence"] = True
    context.user_data["rayon_essence"] = rayon
    await repondre(
        query.message,
        f"⛽ Rayon choisi : **{rayon} km**\n\nEnvoie-moi ta position pour commencer.",
        reply_markup=_bouton_position(),
    )


# ============================================================
# POSITION REÇUE
# ============================================================

async def recevoir_position(update, context):
    lieu = update.message.location
    enregistrer_position(update.effective_chat.id, lieu.latitude, lieu.longitude)

    if context.user_data.pop("attente_parking", False):
        await repondre(update.message, "🅿️ Position reçue. Je cherche les parkings autour de toi...")
        await _afficher_parkings(update.message, _par_position(lieu.latitude, lieu.longitude))
        return

    if context.user_data.pop("attente_essence", False):
        rayon = context.user_data.pop("rayon_essence", 50)
        await repondre(
            update.message,
            f"🔎 **Recherche en cours...**\n\n📍 Rayon : {rayon} km\n"
            "🇫🇷 France · 🇧🇪 Belgique · 🇱🇺 Luxembourg\n⛽ SP95-E10\n\nQuelques secondes...",
        )
        try:
            message = await asyncio.to_thread(afficher_stations, lieu.latitude, lieu.longitude, "e10", rayon)
        except Exception as exc:
            message = f"❌ **Impossible de récupérer les stations pour le moment.**\n\n_{esc_md(texte_erreur(exc, 'essence'))}_"
        await repondre(update.message, message, **PAS_D_APERCU)
        return

    await repondre(
        update.message,
        "📍 **Position enregistrée !**\n\nElle pourra être utilisée pour tes prochains trajets et recherches d'essence.",
    )


def register(app):
    app.add_handler(CommandHandler("trajet", trajet))
    app.add_handler(CommandHandler("essence", essence))
    app.add_handler(CommandHandler("parking", parking))
    app.add_handler(CallbackQueryHandler(bouton_essence_rayon, pattern=r"^essence_rayon_"))
    app.add_handler(CallbackQueryHandler(bouton_essence_trajet, pattern=r"^essence_trajet$"))
    app.add_handler(CallbackQueryHandler(bouton_parking_destination, pattern=r"^parking_destination$"))
    app.add_handler(MessageHandler(filters.LOCATION, recevoir_position))
    return [
        ("trajet", "Lancer l'itinéraire Waze"),
        ("essence", "Comparer les stations (2, 5, 10 ou 50 km)"),
        ("parking", "Trouver des parkings à proximité"),
    ]
