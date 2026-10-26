"""Commandes « simples » : une fonction d'agent → un message.

Pour ajouter une commande, ajoute UNE ligne dans COMMANDES : le handler, le menu
Telegram et la gestion d'erreur sont générés automatiquement.
"""
from functools import partial

from telegram.ext import CommandHandler

from calendar_agent import (
    afficher_cours_de_demain,
    afficher_cours_du_jour,
    afficher_cours_semaine,
    afficher_cours_semaine_prochaine,
    afficher_prochain_cours,
    afficher_prochains_evenements_importants,
    afficher_recherche,
)
from examens_agent import afficher_examens
from todoist_agent import (
    afficher_taches,
    afficher_taches_aujourd_hui,
    afficher_taches_demain,
    afficher_taches_mois,
    afficher_taches_semaine,
)
from utils import appel_securise, repondre, ville_du_jour
from weather import obtenir_meteo

ERR_PLANNING = "❌ Planning indisponible."
ERR_TACHES = "❌ Impossible de récupérer tes tâches."

# nom de commande: (fonction, description dans le menu, message si erreur)
COMMANDES = {
    "prochain":           (afficher_prochain_cours, "Voir mon prochain cours", ERR_PLANNING),
    "importants":         (afficher_prochains_evenements_importants, "Voir les prochains événements importants", ERR_PLANNING),
    "aujourd_hui":        (afficher_cours_du_jour, "Voir mes cours aujourd'hui", ERR_PLANNING),
    "demain":             (afficher_cours_de_demain, "Voir mes cours demain", ERR_PLANNING),
    "semaine":            (afficher_cours_semaine, "Voir mes cours de la semaine", ERR_PLANNING),
    "semaine_prochaine":  (afficher_cours_semaine_prochaine, "Voir mes cours de la semaine prochaine", ERR_PLANNING),
    "examens":            (afficher_examens, "Voir mes prochains examens", ERR_PLANNING),
    "sql":                (partial(afficher_recherche, "sql"), "Voir mes cours de SQL", ERR_PLANNING),
    "python":             (partial(afficher_recherche, "python"), "Voir mes cours de Python", ERR_PLANNING),
    "data":               (partial(afficher_recherche, "data"), "Voir mes cours de Data", ERR_PLANNING),
    "taches":             (afficher_taches, "Voir toutes mes tâches", ERR_TACHES),
    "taches_aujourd_hui": (afficher_taches_aujourd_hui, "Voir mes tâches aujourd'hui", ERR_TACHES),
    "taches_demain":      (afficher_taches_demain, "Voir mes tâches demain", ERR_TACHES),
    "taches_semaine":     (afficher_taches_semaine, "Voir mes tâches de la semaine", ERR_TACHES),
    "taches_mois":        (afficher_taches_mois, "Voir mes tâches du mois", ERR_TACHES),
}


def _fabriquer(fn, erreur):
    async def handler(update, context):
        texte = await appel_securise(fn, erreur)   # thread : le bot ne gèle pas pendant l'appel
        await repondre(update.message, texte)
    return handler


async def meteo(update, context):
    ville = " ".join(context.args).strip() or ville_du_jour()
    texte = await appel_securise(obtenir_meteo, "❌ Impossible de récupérer la météo.", ville)
    await repondre(update.message, texte)


def register(app):
    menu = []
    for nom, (fn, description, erreur) in COMMANDES.items():
        app.add_handler(CommandHandler(nom, _fabriquer(fn, erreur)))
        menu.append((nom, description))
    app.add_handler(CommandHandler("meteo", meteo))
    menu.append(("meteo", "Voir la météo"))
    return menu
