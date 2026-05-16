# Spec: Kalender-Termine ändern & absagen

**Datum:** 2026-05-16
**Status:** Design — freigegeben, Plan ausstehend
**Projekt:** herrlich-ai-platform (Jarvis)

---

## Kontext & Ziel

Nach der Outlook-Migration kann Jarvis Termine **lesen** und **anlegen**. Es
fehlt das Ändern bestehender Termine. Diese Spec ergänzt drei Operationen auf
vorhandenen Outlook-Terminen:

- **Verschieben** — Start-/Endzeit ändern
- **Bearbeiten** — Titel und/oder Ort ändern
- **Absagen** — Termin löschen

Verschieben und Bearbeiten sind technisch dieselbe Operation (`update` — ein
`PATCH` mit den geänderten Feldern), Absagen ist `delete`.

## Nicht-Ziele

- **Ganze Serien ändern.** Nur einzelne Vorkommen. „Verschiebe das Standup am
  Dienstag" ändert genau dieses Vorkommen; die Serie bleibt. „Verschiebe das
  Standup dauerhaft" wird nicht unterstützt.
- **Termine zwischen Kalendern verschieben** — es gibt nur den Standard-Kalender.
- **LLM-gestützte Event-Suche.** Die Treffer-Ermittlung ist deterministisch
  (Substring-Match), kein Haiku-Call wie bei Mail-`smart_search`.

---

## Ansatz

**Event-Suche: deterministisch.** Aus „verschiebe den Zahnarzttermin" muss der
konkrete Termin gefunden werden. `CalendarAgent.search_events(query, start, end)`
holt die Termine im Zeitfenster und filtert per case-insensitivem Substring-Match
auf den Titel. Kein zusätzlicher LLM-Call — ein Tag/eine Woche hat selten >15
Termine, Titel sind kurz. Mehrdeutigkeiten fängt der Auswahl-Dialog ab.

**Flow analog zu Mail-Write.** Suche → 0/1/2–5/>5 Treffer → ggf. Auswahl per
InlineKeyboard → Bestätigungsdialog → Ausführung. Der Bestätigungsdialog zeigt
den gefundenen Termin im Klartext — das ist das Sicherheitsnetz gegen einen
falsch aufgelösten Treffer.

---

## Komponenten & Änderungen

### 1. `Event`-Dataclass (`calendar_agent.py`)

Zwei neue Felder:

```python
@dataclass
class Event:
    id: str            # NEU — MS-Graph-Event-ID, Pflicht für PATCH/DELETE
    title: str
    start: datetime
    end: datetime
    location: Optional[str]
    calendar_name: str
    source: str
    all_day: bool = False
    recurring: bool = False   # NEU — True bei Serien-Vorkommen
```

- `id` steht an erster Stelle (vor den Feldern mit Defaults).
- `recurring` wird aus dem MS-Graph-Feld `type` abgeleitet:
  `recurring = item.get("type") not in (None, "singleInstance")`
  (calendarView liefert `occurrence`/`exception` für Serien-Vorkommen).
- `_to_event` liest `item["id"]` und `item.get("type")`.
- Das `$select` in `_fetch_calendar_view` wird um `id` und `type` erweitert.

### 2. `calendar_agent.py` — drei neue Methoden auf `CalendarAgent`

**`search_events(query, start, end) -> list[Event]`**
- Holt Events via `_fetch_calendar_view(start, end)`.
- Match-Regel: alle Wörter von `query` mit Länge ≥ 3 müssen (case-insensitiv)
  als Substring im Titel vorkommen. Hat `query` kein Wort ≥ 3 Zeichen, gilt der
  ganze `query`-String als Substring-Bedingung.
- Ergebnis nach Startzeit sortiert (kommt bereits sortiert aus `_fetch_calendar_view`).

**`update_event(event_id, new_start=None, new_end=None, new_title=None, new_location=None) -> None`**
- Baut den `PATCH`-Body nur aus den gesetzten Feldern:
  `new_title`→`subject`, `new_start`/`new_end`→`{dateTime, timeZone:"Europe/Berlin"}`,
  `new_location`→`{"location": {"displayName": new_location}}`.
- Sind alle vier Argumente `None` → `ValueError` (Boundary-Guard).
- `PATCH /me/events/{event_id}`, `raise_for_status()`.

**`delete_event(event_id) -> None`**
- `DELETE /me/events/{event_id}`, `raise_for_status()`.

Einzelvorkommen funktionieren ohne Sonderlogik: PATCH/DELETE auf die von
`calendarView` gelieferte Occurrence-ID betreffen genau dieses Vorkommen.

### 3. `router.py` — Kalender-Intent erweitern

`mode` bekommt zwei neue Werte: `"read" | "write" | "update" | "delete"`.

Neue Parameter (nur bei `update`/`delete`):
- `query`: string — markanter Titel-Ausschnitt des Ziel-Termins (z.B. „Zahnarzt",
  „Anna", „Standup"), nicht der ganze Satz.
- `search_start` / `search_end`: ISO-8601 datetime oder null — Suchfenster.
  Bei null setzt `main.py` den Default (jetzt → +30 Tage).

Nur bei `update`:
- `new_start` / `new_end`: ISO-8601 datetime oder null (je null = unverändert).
- `new_title`: string oder null.
- `new_location`: string oder null.
- Mindestens eines der `new_*` muss gesetzt sein.

Beispiele im System-Prompt:
- „Verschiebe den Zahnarzttermin auf 15 Uhr" → mode=update, query="Zahnarzt", new_start=…T15:00
- „Sag den Termin mit Anna morgen ab" → mode=delete, query="Anna", search_start/end=morgen
- „Ändere den Titel von Meeting zu Strategie-Call" → mode=update, query="Meeting", new_title="Strategie-Call"

Der Intent bleibt `calendar` — keine Änderung an der Intent-Whitelist.

### 4. `main.py` — Handler-Flow

**`handle_calendar`** bekommt für `mode in ("update", "delete")` einen neuen
Zweig (ausgelagert in einen Helper `_handle_calendar_modify`, damit
`handle_calendar` nicht weiter aufquillt). Ablauf:

1. `query` fehlt → Fehlermeldung, return.
2. Suchfenster bestimmen: `search_start`/`search_end` oder Default (jetzt → +30 Tage).
3. `events = await asyncio.to_thread(calendar_agent.search_events, query, start, end)`
4. **0 Treffer** → „Keinen Termin gefunden, der zu '{query}' passt." return.
5. **>5 Treffer** → „Mehr als 5 Treffer für '{query}' — bitte präziser." return.
6. **2–5 Treffer** → `_last_calendar_search[chat_id] = {events, mode, params, timestamp}`,
   InlineKeyboard mit `cal:select:{n}`-Buttons senden. return.
7. **1 Treffer** → direkt `_show_calendar_action_confirm(chat_id, event, mode, params)`.

**`_show_calendar_action_confirm(chat_id, event, mode, params)`:**
- Bei `update`: ist `new_start` gesetzt, `new_end` aber nicht → `new_end` =
  `new_start + (event.end - event.start)` (Dauer bleibt erhalten). Pending-Op
  `{type:"update", event_id, new_start, new_end, new_title, new_location}`.
- Bei `delete`: Pending-Op `{type:"delete", event_id, title, start, end}`.
- `_pending_calendar_ops[chat_id] = op`.
- Bei `event.recurring`: eine Zeile „(nur dieser Termin — die Serie bleibt)" im
  Dialog ergänzen.
- InlineKeyboard `cal:action:confirm` / `cal:action:cancel` senden.

**Callback-Vereinheitlichung.** Die in Task 4 der Migration eingeführten
Create-Callbacks `cal:create:confirm`/`cal:create:cancel` werden durch ein
generisches `cal:action:confirm`/`cal:action:cancel` ersetzt:
- `_pending_calendar_ops` bekommt durchgängig ein `type`-Feld
  (`"create" | "update" | "delete"`).
- Der Write-Zweig (`mode == "write"`) setzt `type:"create"`.
- `cal:action:confirm` verzweigt auf `op["type"]`:
  create → `create_event`, update → `update_event`, delete → `delete_event`.
- Neuer Callback `cal:select:{n}`: wählt Event n aus `_last_calendar_search`
  (TTL-Check 3 Min), dann `_show_calendar_action_confirm` — analog `mail:select:{n}`.

Neuer Module-Level-State:
```python
_last_calendar_search: dict[int, dict]   # Multi-Treffer-Auswahl (TTL 3 Min)
```

Der Dispatch-Block `intent == "calendar"` liest die neuen Params (`query`,
`search_start`, `search_end`, `new_*`) und reicht sie an `handle_calendar`.

### 5. Bestätigungsdialoge

**Absagen:**
```
🗑️ Termin absagen?

*Zahnarzt*
14.05.2026 10:00 – 11:00
(nur dieser Termin — die Serie bleibt)      ← nur bei recurring
```
Buttons: ✅ Absagen · ❌ Behalten

**Ändern:** zeigt nur die geänderten Felder als Vorher→Nachher-Diff:
```
📅 Termin ändern?

*Zahnarzt*
Zeit: 14.05. 10:00–11:00 → 14.05. 15:00–16:00
Titel: Zahnarzt → Zahnarzt Dr. Müller         ← nur wenn geändert
Ort: — → Praxis Schwabing                     ← nur wenn geändert
```
Buttons: ✅ Ändern · ❌ Abbrechen

---

## Tests

| Datei | Aktion |
|---|---|
| `tests/test_calendar_read.py` | Fixtures um `id`/`type` ergänzen; `Event.id` und `Event.recurring` im Mapping prüfen. |
| `tests/test_calendar_modify.py` | **Neu** — `search_events` (Treffer, kein Treffer, mehrere, Wort-Match-Regel), `update_event` (PATCH-Body enthält nur geänderte Felder, korrekte Zeitzone), `delete_event` (DELETE auf richtige URL), Fehler-Propagation. httpx-Mocks, Muster wie `test_calendar_write.py`. |

Kein Live-API-Zugang nötig — alles gemockt, läuft in der Standard-Suite.

---

## Doku-Updates (`CLAUDE.md`)

- `calendar_agent.py`-Detailabschnitt: `search_events`/`update_event`/`delete_event` ergänzen.
- Callbacks-Tabelle: `cal:create:*` → `cal:action:confirm`/`cal:action:cancel`;
  `cal:select:{n}` ergänzen.
- Pending-State-Abschnitt: `_pending_calendar_ops` hat jetzt ein `type`-Feld;
  `_last_calendar_search` ergänzen.
- Router-Intent-Beschreibung: `update`/`delete`-Modes des Kalender-Intents.

---

## Fehlerbehandlung

- MS-Graph-Fehler (Netzwerk, 4xx/5xx) propagieren aus `update_event`/`delete_event`
  und werden im `cal:action:confirm`-Callback gefangen → `❌`-Meldung an den Nutzer
  (Muster wie Mail/Create).
- `search_events` gibt bei Fehlern eine leere Liste zurück (wie `get_events`) →
  führt zum „Keinen Termin gefunden"-Pfad.

## Risiken & offene Punkte

- **Occurrence-PATCH/DELETE:** PATCH/DELETE auf eine von `calendarView` gelieferte
  Occurrence-ID soll genau dieses Vorkommen treffen. Der Implementierungsplan
  enthält dafür einen manuellen Live-Test mit einem echten Serientermin.
- **Such-Auflösung:** Der Substring-Match kann den falschen Termin liefern. Der
  Bestätigungsdialog zeigt den Termin im Klartext — der Nutzer sieht vor der
  Ausführung, was getroffen wurde. Bei 2–5 Treffern entscheidet er selbst.
- **Suchfenster-Default (30 Tage):** Termine weiter in der Zukunft werden nicht
  gefunden. Akzeptabel — der Router kann bei Zeitangaben ein größeres Fenster
  setzen, und der Nutzer kann präziser fragen.
