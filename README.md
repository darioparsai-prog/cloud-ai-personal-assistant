# Cloud-Hosted AI Personal Assistant (Telegram Bot)

A 24/7 personal productivity and data retrieval bot hosted on Google Cloud Platform (GCP). It acts as an automated life organizer and decision-support assistant by combining LLM reasoning with live REST API data feeds.

---

## Product Overview & Problem Statement

- Problem: Fragmented daily workflows requiring manual checks across multiple platforms for weather, fuel prices, flight tracking, and schedules.
- Solution: A centralized conversational interface accessible anywhere via Telegram, delivering proactive daily briefings, automated alerts, and on-demand queries powered by AI.
- Target User: Fast-paced professionals and students needing rapid, automated utility without interface clutter.

---

## Key Features

- Automated Daily Briefing: Scheduled morning dispatch compiling calendar items, weather forecasts, and contextual reminders.
- Live Price & Data Tracking: Real-time lookup for regional petrol prices, parking availability, and flight price tracking.
- LLM Intelligence: Natural language processing powered by Google Gemini API to parse complex user requests and deliver concise, action-oriented answers.
- Resilient Cloud Backend: Deployed 24/7 on Google Cloud Platform with automated logging and error monitoring.

---

## Tech Stack & Architecture

- Language & Framework: Python (python-telegram-bot)
- AI & APIs: Google Gemini API, External REST APIs
- Cloud Infrastructure: Google Cloud Platform (GCP)
- Environment & Security: Environment variables via .env (zero hardcoded secrets)

---

## Product Roadmap

- Personalized calendar sync via Google Calendar API
- Automated weekly budget and expense categorization tracker
- Performance monitoring to optimize response latency
