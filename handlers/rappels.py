"""Rappels : /rappel (langage naturel, répétitions), /rappels, /annuler_rappel, boutons Fait / Reporter."""
import html
import logging
from datetime import datetime, time, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackQueryHandler, CommandHandler

import rappel_agent as ra
from config import TZ
from utils import envoyer, maintenant, repondre

log = logging.getLogger(__name__)
H = {"parse_mode": "HTML"}
JOURS_FR = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
MAX_ESSAIS = 5

AIDE = (
    "🔔 <b>Créer un rappel</b>\n\n"
    "<code>/rappel 18:30 appeler maman</code>\n"
    "<code>/rappel demain 9h dentiste</code>\n"
    "<code>/rappel lundi 8h30 rendu projet</code>\n"
    "<code>/rappel 15/12 14h billet de train</code>\n"
    "<code>/rappel dans 2h sortir le linge</code>\n\n"
    "🔁 <b>Répétitions</b>\n"
    "<code>/rappel tous les jours 8h vitamines</code>\n"
    "<code>/rappel chaque lundi 9h poubelles</code>\n"
    "<code>/rappel en semaine 7h30 réveil</code>\n\n"
    "Quand un rappel sonne, tu peux le <b>reporter</b> ou le valider avec les boutons."
)


# ---------- affichage ----------

def _quand(iso: str) -> str:
    dt = datetime.fromisoformat(iso).astimezone(TZ)
    aujourdhui = maintenant().date()
    if dt.date() == aujourdhui:
        jour = "Aujourd'hui"
    elif dt.date() == aujourdhui + timedelta(days=1):
        jour = "Demain"
    else:
        jour = f"{JOURS_FR[dt.weekday()]} {dt:%d/%m/%Y}"
    return f"{jour} à {dt:%H:%M}"


def _liste(chat_id):
    """Retourne (texte HTML, clavier ou None) pour /rappels."""
    liste = ra.obtenir_rappels(chat_id)
    if not liste:
        return "🔔 <b>Mes rappels</b>\n\nAucun rappel programmé.", None
    lignes, boutons = ["🔔 <b>Mes rappels</b>", ""], []
    for r in liste:
        rec = f"\n🔁 {ra.LIBELLES_RECURRENCE[r['recurrence']]}" if r.get("recurrence") else ""
        lignes.append(f"<b>#{r['id']} — {_quand(r['datetime'])}</b>{rec}\n• {html.escape(r['texte'])}\n")
        boutons.append([InlineKeyboardButton(f"🗑️ Supprimer #{r['id']}", callback_data=f"rap:del:{r['id']}")])
    return "\n".join(lignes).rstrip(), InlineKeyboardMarkup(boutons)


def _clavier_rappel(rid):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Fait", callback_data=f"rap:done:{rid}"),
            InlineKeyboardButton("⏰ +10 min", callback_data=f"rap:snooze:{rid}:10"),
            InlineKeyboardButton("⏰ +1 h", callback_data=f"rap:snooze:{rid}:60"),
        ],
        [InlineKeyboardButton("📅 Demain 9h", callback_data=f"rap:snooze:{rid}:demain")],
    ])


# ---------- planification ----------

def _retirer_jobs(job_queue, rid):
    for job in job_queue.get_jobs_by_name(f"rappel_{rid}"):
        job.schedule_removal()


def programmer(job_queue, rappel, delai_min_s=2):
    """(Re)programme un rappel. Un rappel déjà en retard part dans `delai_min_s` secondes."""
    _retirer_jobs(job_queue, rappel["id"])
    quand = max(datetime.fromisoformat(rappel["datetime"]), maintenant() + timedelta(seconds=delai_min_s))
    job_queue.run_once(declencher_rappel, when=quand, data=rappel["id"], name=f"rappel_{rappel['id']}")


async def declencher_rappel(context):
    rid = context.job.data
    r = ra.obtenir_rappel(rid)
    if not r or r.get("envoye_le"):
        return  # supprimé ou déjà traité entre-temps

    now = maintenant()
    prevu = datetime.fromisoformat(r["datetime"])
    retard = now - prevu > timedelta(minutes=2)
    texte = "🔔 <b>Rappel</b>" + (" <i>(en retard)</i>" if retard else "") + f"\n\n{html.escape(r['texte'])}"

    try:
        await envoyer(context.bot, r["chat_id"], texte, reply_markup=_clavier_rappel(rid), **H)
    except Exception:
        # Réseau coupé, etc. : on réessaie (jamais de rappel perdu en silence).
        essais = int(r.get("essais", 0)) + 1
        log.exception("Envoi du rappel #%s impossible (essai %s/%s)", rid, essais, MAX_ESSAIS)
        if essais < MAX_ESSAIS:
            ra.mettre_a_jour(rid, essais=essais)
            context.job_queue.run_once(declencher_rappel, when=60 * essais, data=rid, name=f"rappel_{rid}")
        return

    if r.get("recurrence"):
        prochain = ra.prochaine_occurrence(prevu, r["recurrence"])
        while prochain <= now:              # le bot est resté éteint plusieurs jours ?
            prochain = ra.prochaine_occurrence(prochain, r["recurrence"])
        mis_a_jour = ra.mettre_a_jour(rid, datetime=prochain.isoformat(), essais=0)
        programmer(context.job_queue, mis_a_jour)
    else:
        # On le garde un peu : les boutons « Reporter » en ont besoin. Nettoyé après 48 h.
        ra.mettre_a_jour(rid, envoye_le=now.isoformat(), essais=0)


def restaurer_rappels(app):
    """Au démarrage : reprogramme tout. Les rappels ratés pendant l'arrêt partent « en retard »."""
    ra.nettoyer_envoyes()
    for i, r in enumerate(ra.rappels_a_programmer()):
        programmer(app.job_queue, r, delai_min_s=3 + 2 * i)  # étalé pour ne pas spammer


# ---------- commandes ----------

async def rappel(update, context):
    if not context.args:
        await repondre(update.message, AIDE, **H)
        return
    try:
        quand, recurrence, texte = ra.parser_rappel(context.args, maintenant())
    except ValueError as exc:
        await repondre(update.message, f"❌ {html.escape(str(exc))}\n\nTape /rappel pour voir des exemples.", **H)
        return

    r = ra.creer_rappel(update.effective_chat.id, quand, texte, recurrence)
    programmer(context.job_queue, r)
    rec = f"\n🔁 Répété {ra.LIBELLES_RECURRENCE[recurrence]}" if recurrence else ""
    await repondre(
        update.message,
        f"✅ <b>Rappel programmé !</b>\n\n🔔 {_quand(r['datetime'])}{rec}\n📝 {html.escape(texte)}",
        **H,
    )


async def rappels(update, context):
    ra.nettoyer_envoyes()
    texte, clavier = _liste(update.effective_chat.id)
    await repondre(update.message, texte, reply_markup=clavier, **H)


async def annuler_rappel(update, context):
    if not context.args or not context.args[0].isdigit():
        await repondre(update.message, "❌ Format : <code>/annuler_rappel ID</code>\n\nUtilise /rappels pour voir les IDs.", **H)
        return
    rid = int(context.args[0])
    if not ra.supprimer_rappel(rid, update.effective_chat.id):
        await repondre(update.message, "❌ Rappel introuvable.")
        return
    _retirer_jobs(context.job_queue, rid)
    await repondre(update.message, f"🗑️ Rappel <b>#{rid}</b> annulé.", **H)


# ---------- boutons ----------

async def bouton_rappel(update, context):
    query = update.callback_query
    try:
        _, action, rid, *reste = query.data.split(":")
        rid = int(rid)
    except ValueError:
        await query.answer()
        return

    chat_id = query.message.chat.id
    r = ra.obtenir_rappel(rid)
    if r is None or int(r["chat_id"]) != chat_id:
        await query.answer("Ce rappel n'existe plus.")
        return

    texte = html.escape(r["texte"])

    if action == "done":
        if not r.get("recurrence"):
            ra.supprimer_rappel(rid, chat_id)
        await query.answer("Noté ✅")
        await query.edit_message_text(f"✅ <b>Fait :</b> {texte}", **H)

    elif action == "snooze":
        choix = reste[0] if reste else "10"
        if choix == "demain":
            quand = datetime.combine(maintenant().date() + timedelta(days=1), time(9, 0), tzinfo=TZ)
        else:
            quand = (maintenant() + timedelta(minutes=int(choix))).replace(second=0, microsecond=0)
        if r.get("recurrence"):
            # on ne touche pas à la série : on crée un rappel ponctuel en plus
            nouveau = ra.creer_rappel(chat_id, quand, r["texte"])
        else:
            nouveau = ra.mettre_a_jour(rid, datetime=quand.isoformat(), envoye_le=None, essais=0)
        programmer(context.job_queue, nouveau)
        await query.answer("Reporté ⏰")
        await query.edit_message_text(f"⏰ <b>Reporté à {_quand(quand.isoformat())} :</b> {texte}", **H)

    elif action == "del":
        ra.supprimer_rappel(rid, chat_id)
        _retirer_jobs(context.job_queue, rid)
        await query.answer("Supprimé 🗑️")
        nouveau_texte, clavier = _liste(chat_id)
        await query.edit_message_text(nouveau_texte, reply_markup=clavier, **H)


def register(app):
    app.add_handler(CommandHandler("rappel", rappel))
    app.add_handler(CommandHandler("rappels", rappels))
    app.add_handler(CommandHandler("annuler_rappel", annuler_rappel))
    app.add_handler(CallbackQueryHandler(bouton_rappel, pattern=r"^rap:"))
    return [
        ("rappel", "Programmer un rappel (/rappel seul = aide)"),
        ("rappels", "Voir mes rappels"),
        ("annuler_rappel", "Annuler un rappel"),
    ]
