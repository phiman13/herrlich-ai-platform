# Spec: Kalender-Migration iCloud CalDAV → Outlook (MS Graph)

**Datum:** 2026-05-16
**Status:** Design — freigegeben, Plan ausstehend
**Projekt:** herrlich-ai-platform (Jarvis)

---

## Kontext & Ziel

Philipp hat seinen Kalender vollständig von iCloud auf Outlook umgestellt und
seine Erinnerungen von Apple Erinnerungen auf MS To Do. Jarvis liest und
schreibt Kalender-Termine aktuell über **iCloud CalDAV** (`calendar_agent.py`).
Das muss auf **Microsoft Graph (Outlook)** umgezogen werden.

Die `reminder_write`-Intent schreibt bereits heute in MS To Do
(`tasks_agent.py`) — dort ist nur das irreführende Label "Apple Reminder" zu
korrigieren. Die CalDAV-VTODO-Lesefunktion (`get_reminders_today()`) ist toter
Code und wird ersatzlos entfernt.

## Nicht-Ziele

- Keine Migration auf MS-Graph-Kalender mit Mehrkalender-Unterstützung —
  Jarvis nutzt ausschließlich den **Standard-Kalender** (`/me/calendar`).
- Keine Änderung an `tasks_agent.py` außer der Doku/Label-Korrektur.
- Keine Änderung an Lese-Formatierung (`format_calendar_response`,
  `detect_calendar_window` bleiben unverändert — sie arbeiten auf `Event`).

---

## Architektur-Entscheidung

**Ansatz A — Backend-Abstraktion auflösen.**

`calendar_agent.py` enthält heute ein `CalendarBackend`-ABC mit genau einer
Implementierung (`ICloudCalDAVBackend`) — vorausschauende Abstraktion, die gegen
YAGNI verstößt. Mit nur noch Outlook wird sie aufgelöst:

- `CalendarBackend` (ABC) und `ICloudCalDAVBackend` entfallen.
- `CalendarAgent` spricht **direkt** MS Graph — analog zu `tasks_agent.py`.
- Die Public-API von `CalendarAgent` bleibt stabil
  (`get_events`, `get_next_event`, `create_event`), damit Aufrufer
  (`main.py`, `briefing_agent.py`, `proactive_agent.py`) minimal betroffen sind.

HTTP über `httpx` (synchron, wie `tasks_agent.py`); Aufruf aus `main.py`
weiterhin via `asyncio.to_thread`. Auth über
`microsoft_auth.get_access_token()`.

---

## Komponenten & Änderungen

### 1. `agents/calendar_agent.py` — Neuschrieb

**Behalten:** `Event`-Dataclass, `BERLIN`/`UTC`-Konstanten, `_to_berlin()`.
- `Event.source` → `"outlook"`.
- `Event.calendar_name` bleibt im Dataclass (Kompatibilität mit
  `format_calendar_response`), wird mit dem Anzeigenamen des Standard-Kalenders
  befüllt.

**Entfernen:** `CalendarBackend`, `ICloudCalDAVBackend`,
`_MULTIDAY_LOOKBACK_DAYS`, `_default_backends()`, `_deduplicate()`,
`get_reminders_today()`, `get_calendar_names()`.

**`CalendarAgent` — neue Implementierung:**

| Methode | MS-Graph-Call |
|---|---|
| `get_events(start, end)` | `GET /me/calendarView` |
| `get_next_event()` | `get_events(now, now+60d)` → erstes Event mit `start >= now` |
| `create_event(title, start_dt, end_dt)` | `POST /me/events` |

Konstruktor ohne Argumente (`CalendarAgent()`) — keine Backend-Liste mehr.

**Lesen — `GET /me/calendarView`:**
```
GET https://graph.microsoft.com/v1.0/me/calendarView
  ?startDateTime=<ISO>&endDateTime=<ISO>
  &$orderby=start/dateTime&$top=100
  &$select=subject,start,end,isAllDay,location
Header:
  Authorization: Bearer <token>
  Prefer: outlook.timezone="Europe/Berlin"
```
- `calendarView` expandiert Serien- und Multi-Day-Termine serverseitig — der
  `_MULTIDAY_LOOKBACK_DAYS`-Workaround entfällt.
- `Prefer: outlook.timezone` → zurückgegebene `dateTime`-Werte sind in
  Berlin-Zeit (Format `2026-05-16T10:00:00.0000000`, ohne Offset) → naiv parsen,
  `BERLIN`-tz anhängen.
- `@odata.nextLink` folgen, falls vorhanden (sonst genügt `$top=100`).
- Mapping: `subject`→`title`, `start`/`end`→datetime, `isAllDay`→`all_day`,
  `location.displayName`→`location`.
- Fehler (Netzwerk, 4xx/5xx, fehlender Token) → leere Liste zurückgeben +
  Warning loggen (heutiges Verhalten).

**Schreiben — `POST /me/events`:**
```json
{
  "subject": "<title>",
  "start": {"dateTime": "2026-05-17T10:00:00", "timeZone": "Europe/Berlin"},
  "end":   {"dateTime": "2026-05-17T11:00:00", "timeZone": "Europe/Berlin"}
}
```
- Kein `calendar_name`-Parameter mehr — Termin landet im Standard-Kalender.
- Fehler → Exception werfen (heutiges Verhalten; wird im Callback gefangen).

### 2. `agents/microsoft_auth.py`

`SCOPES` um `Calendars.ReadWrite` erweitern:
```python
SCOPES = ["Mail.ReadWrite", "Mail.Send", "Tasks.ReadWrite",
          "Tasks.ReadWrite.Shared", "Calendars.ReadWrite"]
```

⚠️ **Re-Auth erforderlich:** MSAL upgraded gecachte Tokens nicht automatisch
auf neue Scopes. Nach Deploy einmalig
`https://herrlich.dev/oauth/microsoft/login?secret=<OAUTH_LOGIN_SECRET>`
aufrufen. Vorher gibt MS Graph für Kalender-Calls `403` zurück → bis zur
Re-Auth liefert `get_events` leere Listen, `create_event` schlägt fehl.

### 3. `agents/router.py`

- Intent `"calendar"`-Beschreibung: "Apple Calendar via CalDAV" → "Outlook-Kalender".
- `{CALENDAR_NAMES}`-Platzhalter, dessen Injection in `_build_system_prompt`
  und die Helper-Funktion `_get_calendar_names()` entfernen.
- `calendar_name`-Parameter aus der Intent-Parameter-Doku streichen.
- `reminder_write`-Label "Apple Reminder / Erinnerung" → "Erinnerung (MS To Do)".

### 4. `agents/main.py` — Bestätigungsdialog für Kalender-Schreibaktionen

Neu: Termin-Erstellung erhält einen Confirm-Dialog (analog Mail-Write-Pattern).

**Neuer Module-Level-State:**
```python
_pending_calendar_ops: dict[int, dict] = {}   # chat_id -> {title, start, end}
```

**`handle_calendar` — Signatur & Write-Branch:**
- `calendar_name`-Parameter aus der Funktionssignatur entfernen.
- Write-Branch: nach Validierung (`title` + `start` vorhanden, `end` default
  `start+1h`) **nicht mehr direkt ausführen**, sondern:
  - `_pending_calendar_ops[chat_id] = {"title", "start", "end"}` (datetime-Objekte)
  - InlineKeyboard senden:
    ```
    📅 *Termin erstellen?*

    *<title>*
    <start: %d.%m.%Y %H:%M> – <end: %H:%M>
    ```
    Buttons: `✅ Erstellen` (`cal:create:confirm`) · `❌ Abbrechen` (`cal:create:cancel`).
- Read-Branch unverändert.

**`handle_callback` — neue Callbacks:**
- `cal:create:confirm`: `_pending_calendar_ops.pop(chat_id)`; bei `None` →
  "⚠️ Keine ausstehende Aktion gefunden."; sonst
  `await asyncio.to_thread(calendar_agent.create_event, title, start, end)`,
  Nachricht via `edit_message_text` auf Erfolg/Fehler. Exceptions fangen +
  loggen (Muster wie `mail:action:confirm`).
- `cal:create:cancel`: `_pending_calendar_ops.pop(chat_id, None)`;
  `edit_message_text("❌ Abgebrochen.")`.

**Intent-Dispatch (`intent == "calendar"`):** Aufruf von `handle_calendar` ohne
`calendar_name`-Argument.

### 5. `agents/requirements.txt`

Entfernen (nur vom alten CalDAV-Code genutzt — per Grep verifiziert):
`caldav==3.1.0`, `icalendar==7.0.3`, `icalendar-searcher==1.0.5`.

### 6. Environment-Variablen

Nicht mehr benötigt: `ICLOUD_USER`, `ICLOUD_APP_PASSWORD`, `CALENDAR_WHITELIST`.
- Aus `CLAUDE.md`-Env-Tabelle entfernen.
- Aus `.env.example` entfernen, falls vorhanden.
- Philipp entfernt sie manuell aus der VPS-`.env`.

---

## Tests

| Datei | Aktion |
|---|---|
| `tests/test_calendar_reminders.py` | **Löschen** — `get_reminders_today()` entfällt. |
| `tests/test_calendar_write.py` | **Neu schreiben** — `httpx.post`-Mock + `get_access_token`-Patch (Muster aus `test_mail_write.py`); assertet MS-Graph-`POST /me/events`-Payload. |
| `tests/test_calendar_read.py` | **Neu** — `httpx.get`-Mock liefert `calendarView`-JSON; assertet `Event`-Mapping: Titel, Zeitzone, `all_day`, `location`, Sortierung. |

Kein Live-API-Zugang nötig (gemockt) — laufen in der Standard-Test-Suite.

---

## Doku-Updates (`CLAUDE.md`)

- `calendar_agent.py`-Beschreibung: CalDAV → MS Graph.
- Env-Variablen-Tabelle: `ICLOUD_*` + `CALENDAR_WHITELIST` raus.
- "MS Graph OAuth"-Abschnitt: `Calendars.ReadWrite` zu Scopes; Hinweis, dass
  Kalender jetzt über Graph statt CalDAV läuft.
- "Bekannte Eigenheiten": CalDAV-Reminder-Notiz entfernen; Hinweis ergänzen,
  dass Kalender-Schreibaktionen jetzt einen Confirm-Dialog haben.
- Callback-Tabelle: `cal:create:confirm` / `cal:create:cancel` ergänzen.
- Pending-State-Abschnitt: `_pending_calendar_ops` ergänzen.

---

## Risiken & offene Punkte

- **Re-Auth-Fenster:** Zwischen Deploy und Re-Auth ist der Kalender nicht
  verfügbar (403 → leere Listen). Akzeptabel, da kurz und einmalig.
- **Token-Cache:** Falls die Re-Auth vergessen wird, schlägt der Kalender
  stumm fehl (leere Liste). Der Plan sollte einen manuellen Verifikations-Schritt
  nach Deploy enthalten ("Termin heute" abfragen).
- **Zeitzonen-Parsing:** `calendarView` mit `Prefer`-Header liefert lokale Zeit
  ohne Offset — das Parsing muss naive Strings korrekt als Berlin-Zeit
  interpretieren. In `test_calendar_read.py` explizit abdecken.
