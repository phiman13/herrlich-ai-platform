# Jarvis Second Brain — Design Spec

**Date:** 2026-05-12
**Status:** Approved — Backlog (Seed-Befüllung ausstehend)
**Builds on:** `2026-05-07-jarvis-persistent-user-profile-design.md` (bereits implementiert)

## Goal

Das bestehende `profile_agent.py` wird in zwei Dimensionen erweitert:
1. **Reichhaltigeres Profil** — neue Kategorien (Familie & Umfeld, Werte & Überzeugungen, Routinen & Alltag) + manueller Seed mit echten Inhalten
2. **`/profil`-Telegram-Befehl** — Philipp kann sein Profil jederzeit ansehen und via Freitext aktualisieren

Das Konzept orientiert sich am "AI Second Brain"-Ansatz (kuratierte Markdown-Dateien als explizite Kontext-Quelle), adaptiert für Jarvis als Single-User-Telegram-Bot.

## Was sich ändert

### 1. Profil-Kategorien (Erweiterung)

**Aktuell** (6 Abschnitte):
- Beruf & Rolle, Fähigkeiten & Werkzeuge, Projekte
- Interessen & Hobbys, Kommunikationsstil, Laufende Ziele

**Neu** (9 Abschnitte — 3 neue):
- Beruf & Rolle, Fähigkeiten & Werkzeuge, Projekte
- **Familie & Umfeld** *(neu)*
- Interessen & Hobbys
- **Werte & Überzeugungen** *(neu)*
- **Routinen & Alltag** *(neu)*
- Kommunikationsstil, Laufende Ziele

`_DEFAULT_PROFILE` in `profile_agent.py` entsprechend erweitern.

### 2. Manueller Seed

Die Profil-Datei auf dem VPS (`/var/lib/jarvis/.jarvis/user_profile.md`) wird einmalig mit echten Inhalten befüllt — im Chat-Interview erarbeitet und via rsync hochgeladen. Der Auto-Update-Mechanismus (Haiku nach Gesprächen) bleibt aktiv und reichert das Profil weiter an.

**Stand der Seed-Befüllung:**
- Beruf & Rolle: ✅ erfasst (siehe unten)
- Alle anderen Abschnitte: ausstehend

**Beruf & Rolle (bereits bekannt):**
> Strategischer Unternehmensberater im deutschen Gesundheitswesen. Kunden: Krankenkassen, Software-Unternehmen, Verbände, Fachverlage. Rolle: Projektleitung und Gesamtverantwortung für Strategie-Projekte. Arbeitgeber: Forward Strategy GmbH, Berlin.

### 3. `/profil`-Telegram-Befehl

**View:** `/profil` ohne Argument → Jarvis sendet das aktuelle Profil als Nachricht (ggf. aufgeteilt bei >4096 Zeichen).

**Update:** `/profil <freitext>` → Haiku integriert den Text ins Profil via `profile_agent.update()`, Jarvis bestätigt kurz was sich geändert hat.

**Implementierung:**
- Präfix-Check in `_process_text()` in `main.py` — kein Router-Call nötig (Befehl ist eindeutig)
- `profile_agent.update()` wird direkt aufgerufen (statt nur als Background-Task)
- Bestätigung: Haiku-Diff-Prompt ("Was hat sich gegenüber dem alten Profil geändert?" → 1 Satz)

## File Map

| File | Änderung |
|---|---|
| `agents/profile_agent.py` | `_DEFAULT_PROFILE` um 3 neue Abschnitte erweitern |
| `agents/main.py` | `/profil`-Präfix-Check vor Router-Call; View + Update-Handler |
| `user_profile.md` auf VPS | Einmalig manuell befüllen + hochladen |

## Out of Scope

- Multi-File-Split (personal.md / work.md) — kein messbarer Nutzen für diesen Use Case
- Voice.md / Identity.md-Trennung — Overkill für Telegram-Bot
- Finanzen-Kategorie — zu sensitiv
- Profil-Versioning / History
