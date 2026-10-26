"""Texte libre → assistant IA (Gemini). Lectures directes, écritures après confirmation par bouton."""
import asyncio
import logging
import time
import uuid

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackQueryHandler, CommandHandler, MessageHandler, filters

import llm_agent
from security import cooldown, texte_erreur
from utils import esc_md, repondre

log = logging.getLogger(__name__)

MEMOIRE_S = 30 * 60          # l'historique est oublié après 30 min d'inactivité
MAX_ENTREES = 8              # 4 échanges gardés
EXPIRATION_ACTION_S = 10 * 60
MAX_ACTIONS = 3

REPLI = "Utilise les commandes classiques en attendant (/cours, /taches, /rappel, /vol…)."


# ---------- mémoire courte ----------

def _historique(context):
    mem = context.user_data.get("llm_hist")
    if not mem or time.monotonic() - mem["t"] > MEMOIRE_S:
        return []
    return mem["msgs"]


def _memoriser(context, question, reponse):
    msgs = (_historique(context) + [{"role": "user", "text": question}, {"role": "model", "text": reponse}])[-MAX_ENTREES:]
    while msgs and msgs[0]["role"] != "user":
        msgs.pop(0)
    context.user_data["llm_hist"] = {"t": time.monotonic(), "msgs": msgs}


# ---------- affichage ----------

def _clavier_url(sortie):
    if sortie.get("url"):
        return InlineKeyboardMarkup([[InlineKeyboardButton(sortie.get("url_label") or "🔗 Ouvrir", url=sortie["url"])]])
    return None


async def _afficher(message, sortie):
    await repondre(message, sortie["texte"], reply_markup=_clavier_url(sortie), disable_web_page_preview=True)


# ---------- message libre ----------
import re

def _nettoyer_markdown_brut(texte: str) -> str:
    # Transforme les titres ### Titre en 📌 TITRE
    texte = re.sub(r"^#{1,6}\s*(.+)$", r"📌 \1", texte, flags=re.MULTILINE)
    # Supprime les ** du gras non interprété en mode texte brut
    texte = texte.replace("**", "")
    # Remplace les puces * en début de ligne par •
    texte = re.sub(r"^\s*\*\s+", "• ", texte, flags=re.MULTILINE)
    return texte.strip()


@cooldown(2)
async def message_libre(update, context):
    if not update.message:
        return
    question = (update.message.text or "").strip()
    if not question:
        return
    if not llm_agent.disponible():
        await repondre(update.message, "🤖 L'assistant IA n'est pas configuré (GEMINI_API_KEY absente). " + REPLI, parse_mode=None)
        return

    await update.effective_chat.send_action("typing")
    try:
        res = await asyncio.to_thread(llm_agent.traiter, update.effective_chat.id, question, _historique(context))
    except llm_agent.LLMIndisponible as exc:
        log.warning("IA indisponible : %s", exc)
        await repondre(update.message, f"🤖 IA indisponible : {exc}.\n\n{REPLI}", parse_mode=None)
        return
    except Exception as exc:
        await repondre(update.message, f"❌ {esc_md(texte_erreur(exc, 'llm'))}\n\n{REPLI}")
        return

    _memoriser(context, question, res.resume)

    if res.texte:
        await repondre(update.message, _nettoyer_markdown_brut(res.texte), parse_mode=None)
    for sortie in res.sorties:
        await _afficher(update.message, sortie)

    en_attente = context.user_data.setdefault("llm_actions", {})
    # Nettoyage des vieilles actions expirées pour éviter les fuites en mémoire
    maintenant_mono = time.monotonic()
    for k in [k for k, v in en_attente.items() if maintenant_mono - v["t"] > EXPIRATION_ACTION_S]:
        en_attente.pop(k, None)

    for action in res.actions[:MAX_ACTIONS]:
        token = uuid.uuid4().hex[:8]
        en_attente[token] = {"action": action, "t": maintenant_mono}
        clavier = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Confirmer", callback_data=f"llm:ok:{token}"),
            InlineKeyboardButton("❌ Annuler", callback_data=f"llm:no:{token}"),
        ]])
        await repondre(update.message, f"{action['resume']}\n\nJe confirme ?", parse_mode=None, reply_markup=clavier)


# ---------- boutons Confirmer / Annuler ----------

async def bouton_llm(update, context):
    query = update.callback_query
    try:
        _, decision, token = query.data.split(":", 2)
    except ValueError:
        await query.answer()
        return

    entree = context.user_data.get("llm_actions", {}).pop(token, None)
    if not entree or time.monotonic() - entree["t"] > EXPIRATION_ACTION_S:
        await query.answer("Action expirée : redemande-moi.", show_alert=True)
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
        return

    action = entree["action"]
    if decision != "ok":
        await query.answer("Annulé")
        await query.edit_message_text(f"❌ Annulé\n\n{action['resume']}")
        return

    await query.answer("C'est parti…")
    await query.edit_message_text(f"⏳ {action['resume']}")
    chat_id = query.message.chat.id
    try:
        r = await asyncio.to_thread(llm_agent.executer, action["nom"], action["args"], chat_id)
    except Exception as exc:
        await query.edit_message_text(f"❌ Échec\n\n{action['resume']}")
        await repondre(query.message, f"❌ {esc_md(texte_erreur(exc, 'llm action'))}")
        return

    await query.edit_message_text(f"✅ {action['resume']}")
    if r.get("programmer"):
        from . import rappels as h_rappels
        h_rappels.programmer(context.job_queue, r["programmer"])
    if r.get("retirer"):
        for job in context.job_queue.get_jobs_by_name(f"rappel_{r['retirer']}"):
            job.schedule_removal()
    await _afficher(query.message, {"texte": r["message"], "url": r.get("url"), "url_label": r.get("url_label")})


# ---------- diagnostic & reset ----------

@cooldown(10)
async def cmd_modeles(update, context):
    try:
        modeles = await asyncio.to_thread(llm_agent.lister_modeles)
    except Exception as exc:
        await repondre(update.message, f"❌ {esc_md(texte_erreur(exc, 'llm_modeles'))}")
        return
    actuel = llm_agent._modele()
    lignes = "\n".join(f"{'👉' if m == actuel else '•'} {m}" for m in modeles) or "(aucun)"
    await repondre(
        update.message,
        f"🤖 Modèles Gemini Texte/Outils disponibles :\n\n{lignes}\n\n"
        f"Modèle actif : {actuel} (repli automatique activé).\n"
        f"Pour forcer un modèle : GEMINI_MODEL=nom dans .env.",
        parse_mode=None,
    )


async def cmd_reset(update, context):
    context.user_data.pop("llm_hist", None)
    context.user_data.pop("llm_actions", None)
    await repondre(update.message, "🧹 Mémoire de conversation IA réinitialisée.", parse_mode=None)


def register(app):
    app.add_handler(CommandHandler("llm_modeles", cmd_modeles))
    app.add_handler(CommandHandler("llm_reset", cmd_reset))
    app.add_handler(CallbackQueryHandler(bouton_llm, pattern=r"^llm:"))
    # group=1 : s'exécute APRÈS les handlers de texte du groupe 0 (facture), jamais à leur place
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_libre), group=1)
    return [
        ("llm_reset", "Réinitialiser la mémoire de conversation IA"),
    ]