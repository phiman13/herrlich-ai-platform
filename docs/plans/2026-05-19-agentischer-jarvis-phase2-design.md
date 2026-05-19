# Agentischer Jarvis — Phase 2 Design

**Status:** Design — freigegeben 2026-05-19
**Übergeordnet:** `docs/plans/2026-05-18-agentischer-jarvis-design.md` (SSoT aller Phasen)
**Umsetzung:** ab sofort — eigener Umsetzungsplan folgt (writing-plans)
**Backlog:** P1 „Agentischer Jarvis — Phase 2 & 3" in `BACKLOG.md`

## Ziel

Phase 1 hat den Gesprächspfad (`personal`/`work`/`research`) auf einen echten
Agenten umgestellt; der Router blieb vorgelagert und routet strukturierte Intents
(`mail`, `calendar`, `tasks`, …) unverändert über ihre Handler. Verklassifiziert
der Router eine Frage, erreicht sie den Agenten nicht — der bekannte
Fehlklassifikations-Fehlmodus.

Phase 2 baut die strukturierten Handler einzeln zu Agenten-Tools um. Mit jeder
Konvertierung übernimmt der Agent den Intent produktiv. Endzustand: alle Intents
agentisch, der Router funktionslos umgangen. Phase 3 löscht den Router dann samt
`_process_text`-Kollaps.

## Kernentscheidungen

| Thema | Wahl | Begründung |
|---|---|---|
| **Spec-Scope** | Ganz Phase 2 in einem Spec (8 Konvertierungen + Write-Confirm) | Ein Spec ist billig, das SSoT-Design existiert. Der Umsetzungsplan wird ohnehin Mini-Zyklen — die erste Konvertierung (`weather`) ist de facto der Pilot. |
| **Übergabe-Modell** | Inkrementell — konvertierter Intent wandert sofort in `_AGENT_INTENTS` | Pro Schritt sofort Wert; Phase 3 wird zum reinen Router-Entfall ohne Verhaltenssprung. Risiko klein & isoliert pro Schritt, git-revertierbar. |
| **Ansatz** | Fähigkeits-Tools, Agent orchestriert | Die Orchestrierungs-Logik der Handler (Suche→Disambiguierung→Confirm) entfällt — der Agent macht das per mehreren Tool-Calls. Genau die Design-Absicht. |
| **`memory`-Intent** | Eigenes `memory`-Tool ergänzen (list/delete) | Das Design ließ den expliziten `memory`-Intent ohne Zuhause. Mit eigenem Tool kann Phase 3 den Router wirklich komplett entfernen. |
| **read/write-Gate** | Tool klassifiziert selbst; Permission-Hook bleibt reine Allowlist | Sauberer als „Permission-Hook prüft die Aktion" — der echte Gate ist Vormerken + Lauf-Ende-Confirm. |
| **`JARVIS_AGENT_ENABLED`** | Flag in Phase 2 abgeschafft (Plan 1) | „Alten Handler löschen" und „Flag-aus-Fallback behalten" schließen sich aus. Der Agent-Pfad wird dauerhaft für alle Intents; Rollback = git revert + Redeploy. `chat_handler.py` (Phase-1-Konversations-Handler) entfällt damit. |

## Bewusst benannte Kosten

- **Latenz/Kosten multiplizieren sich.** „Wie wird das Wetter?" heute: 1 Haiku-Route
  + 1 API-Call, ~1 s. Nach Konvertierung: Haiku-Route + voller Sonnet-Loop (≥2
  Roundtrips) + Tool-Call, ~5–10 s, echte Token-Kosten — bei jedem trivialen Intent.
  Das Design akzeptiert das bewusst. Maßnahme: nach jeder Konvertierung kurz messen
  (Latenz, grobe Token), nicht spekulativ optimieren (Modell-Tiering = später).
- **Disambiguierungs-UX.** Der heutige „mehrere Treffer → InlineKeyboard zum
  Auswählen"-Flow (Mail/Kalender) entfällt. Der Agent löst Mehrdeutigkeit im Text
  auf. **Kein Rückschritt:** der gebündelte Write-Confirm am Lauf-Ende zeigt das
  konkrete Ziel („Mail von X vom 3.5. löschen?") — ein falscher Agenten-Pick wird
  vor der Ausführung abgefangen.

## 1 — Tool-Architektur & Modulstruktur

`agent_tools.py` (eine Datei) würde mit 9 Tools platzen. Stattdessen ein Paket:

```
agents/tools/
  __init__.py        Registry + build_mcp_server(chat_id) + permission_hook
  workspace_tool.py  (aus agent_tools.py hierher verschoben)
  weather_tool.py    news_tool.py    tasks_tool.py    briefing_tool.py
  memory_tool.py     mail_tool.py    calendar_tool.py coding_tool.py
```

- **9 MCP-Tools** (`workspace` + 8 neue). `web` bleibt das eingebaute
  `WebSearch`/`WebFetch` (in `allowed_tools`).
- Jedes Tool-Modul exportiert eine `make_<name>_tool(chat_id)`-Factory und —
  falls es Schreib-Aktionen hat — ein `execute_write(action, params) -> str`.
- Tools geben Text-Content zurück (`{"content": [{"type": "text", "text": …}]}`),
  Fehler als `FEHLER: …`-Präfix (wie `workspace` heute).
- Jedes Tool nimmt einen `action`-Parameter plus fähigkeits-spezifische Parameter.

`agent_tools.py` entfällt; `agent.py` importiert aus `agents/tools/`.

## 2 — Chat-Scoping

MCP-Tools bekommen nur `args` — für den Pending-Store brauchen sie die `chat_id`.

**Lösung:** `build_mcp_server(chat_id)` baut die Tools pro Lauf frisch, jede
`make_<name>_tool(chat_id)`-Factory schließt `chat_id` ein. `run_agent` ruft
`build_mcp_server()` ohnehin schon pro Nachricht auf. Kein contextvar-Hidden-State,
explizit. 9 Tools pro Nachricht zu bauen ist vernachlässigbar.

## 3 — Read vs. Write: Vormerk-/Confirm-Mechanik

Neuer Store in `app_state.py`:

```python
_pending_agent_actions: dict[int, dict]   # chat_id -> {actions: [...], timestamp}
# action: {"tool": "mail", "action": "delete",
#          "label": "Mail von X vom 3.5. löschen", "params": {...}}
```

**Ablauf:**

- **Read-Aktion** → Tool führt sofort aus (via Unter-Agent), gibt Daten zurück.
- **Write-Aktion** → Tool führt *nicht* aus, hängt an `_pending_agent_actions[chat_id]`
  an, gibt zurück: *„Vorgemerkt: <label>. Wird nach Philipps Bestätigung ausgeführt
  — du musst nicht warten."* Das Tool klassifiziert read/write selbst (Set von
  Write-Action-Namen pro Modul).
- **Lauf-Ende in `run_agent`:**
  - Pending-Actions vorhanden → finaler Agent-Text + nummerierte Liste der
    Aktionen + InlineKeyboard `✅ Bestätigen` / `❌ Abbrechen`
    (Callback `agent:confirm` / `agent:cancel`).
  - Keine Pending → senden wie heute.
  - Lauf mit Fehler → Pending verwerfen, keinen halbgaren Plan zeigen.
- **Confirm-Callback** (`callbacks.py`, neu `agent:confirm` / `agent:cancel`):
  - `agent:confirm` → Pending poppen, TTL prüfen (3 Min), Aktionen iterieren, je
    via `execute_write` des Tool-Moduls ausführen, Nachricht mit Sammel-Ergebnis
    editieren. Agent wird **nicht** fortgesetzt (Design: Fortsetzung = v2).
  - `agent:cancel` → Pending verwerfen, „❌ Abgebrochen.".

**Permission-Hook:** bleibt eine reine Allowlist der 9 Tool-Namen (verweigert
Unbekanntes wie `Bash`). Er prüft *nicht* die Aktion — das Tool klassifiziert
read/write selbst.

**Restart-Verhalten:** Der Pending-Store ist in-memory (wie die heutigen
`_pending_*`-Dicts). Ein Restart im 3-Min-Confirm-Fenster verliert die Vormerkung
— akzeptabel, wie heute. Kein SQLite für einen 3-Minuten-Confirm.

**Nebenläufigkeit:** Ein neuer Agentenlauf für denselben Chat ersetzt den
Pending-Store (verwirft alte, unbestätigte Aktionen) — wie heute „neue Suche
überschreibt". Der per-Chat-`asyncio.Lock` serialisiert Läufe; der Confirm-Callback
läuft außerhalb des Locks, berührt nur das Pending-Dict.

## 4 — Konvertierungs-Sequenz & dispatch/router

Reihenfolge nach Risiko. Jede Konvertierung = ein Mini-Zyklus:
**Tool-Modul schreiben → Unit-Tests → `dispatch.py` (`_AGENT_INTENTS` += Intent) →
toten Handler-Code löschen → Deploy via GitHub-Webhook → Telegram-Smoke-Test.**
Jeder Zyklus ist git-revertierbar.

| # | Intent | Art | Beweist / Besonderheit |
|---|---|---|---|
| 1 | `weather` | read-only | Pilot — Tool-Muster, Chat-Scoping, `_AGENT_INTENTS`-Eintrag, Set-Konvergenz |
| 2 | `news` | read-only | — |
| 3 | `tasks` | read + write | Erstes Write-Tool — Vormerk/Confirm, `agent:confirm`, `execute_write`. `reminder_write` faltet hier rein |
| 4 | `briefing` | read-only | Teilt `build_briefing()` mit dem Scheduler-Job (bleibt deterministisch) |
| 5 | `memory` | read + write | `list` (read), `delete` (write) |
| 6 | `mail` | schwere Writes | Nutzt die bewiesene Confirm-Mechanik; `mail_handler.py` schrumpft stark |
| 7 | `calendar` | schwere Writes | Wie `mail` |
| 8 | `coding` | Sonderfall | Siehe Sektion 5 |

**Set-Konvergenz:** Pro Zyklus wandert der Intent in `_AGENT_INTENTS`. Da
agentische Intents History + Memory brauchen, wandert er zugleich in
`_MEMORY_INTENTS` und `_HISTORY_INTENTS` — die drei Sets konvergieren. Nebeneffekt:
das liefert den Backlog-P2-Punkt „Gesprächsverlauf für alle Intents" gratis mit.

**Router in Phase 2:** bleibt physisch da, klassifiziert weiter. Seine
dynamische Kontext-Erzeugung (Kalender-Namen, To-Do-Listen, Mail-Ordner im
System-Prompt) wird für agentische Intents irrelevant — der Agent entdeckt das
selbst via Tool-Calls (z. B. `tasks` action=`list_lists`). Mit der letzten
Konvertierung klassifiziert der Router nur noch in agentische Intents → totes
Gewicht. **Phase-2-Endzustand: alle Intents agentisch, Router umgangen.**
Phase 3 löscht `router.py` + lässt `_process_text` kollabieren.

Der `confidence < 5`-Fallback bleibt in Phase 2 (der Router gatet noch
nicht-konvertierte Intents), fällt mit dem Router in Phase 3.

**Phase-1-Scaffolding-Abbau (Plan 1, vor der ersten Konvertierung):** Das
Feature-Flag `JARVIS_AGENT_ENABLED` wird abgeschafft — der Agent-Pfad ist
dauerhaft für `personal`/`work`/`research`. Das macht `chat_handler.py` (die
Phase-1-Single-shot-Handler `handle_personal/work/research` + `ask_claude`) tot;
es wird mitgelöscht. Rollback ab Phase 2 = git revert + Redeploy, nicht mehr der
Env-Schalter. Dieser Abbau ist die Voraussetzung dafür, dass konvertierte Handler
pro Mini-Zyklus wirklich gelöscht werden können.

**Handler-/Datei-Aufräumen pro Zyklus:** `intent_handlers.py` schrumpft (weather,
news, tasks, briefing, memory, coding-Handler entfallen); `mail_handler.py` /
`calendar_handler.py` schrumpfen auf nahe Null (die Orchestrierung löst sich auf,
die Low-Level-Calls leben in `mail_agent.py` / `calendar_agent.py`). Die alten
`*:action:confirm` / `*:select:`-Callbacks entfallen mit der Mail-/Kalender-
Konvertierung; `callbacks.py` behält nur `push:`, `dismiss` und die neuen
`agent:confirm` / `agent:cancel`.

## 5 — `coding`-Tool (Sonderfall)

`coding` hat heute drei Modi. Als Tool:

- `action=query` (Backlog/Todos lesen) → read → sofort ausführen, Text zurück.
- `action=add_backlog` → write → vormerken → Confirm → `execute_write` ruft
  `add_backlog_item`.
- `action=run` (Claude-Code-Lauf) → write → vormerken → Confirm. Bei Bestätigung
  startet `execute_write` `run_coding_action` fire-and-forget (postet eigene
  Progress-Updates + „Pushen"-Button wie heute). Der Agent wartet **nicht**.
  `claude-guard` bleibt im Subprozess aktiv — unverändert.

**Hedge:** Zeigt der Umsetzungsplan, dass `coding`s Session-/Callback-Verflechtung
zu sehr verknotet, wird `coding` ein eigenes Phase-2.5-Mini-Spec — Phase 3 wartet
dann darauf. Deshalb steht `coding` als letzter Zyklus.

## 6 — Tests & Erfolgskriterien

**Unit-Tests (deterministisch):**

- Pro Tool-Modul: read-Aktion → Daten (Unter-Agent gemockt); write-Aktion → korrekt
  vorgemerkt + „vorgemerkt"-Text zurück + Write-Methode des Unter-Agenten **nicht**
  aufgerufen.
- `execute_write` pro Write-Tool: führt via Unter-Agent aus (gemockt).
- Permission-Hook: erlaubt alle 9 Jarvis-MCP-Tools, verweigert Unbekanntes.
- Pending-Store: Append, TTL-Ablauf, Overwrite durch neuen Lauf.
- Lauf-Ende-Confirm: Pending → Keyboard gebaut; keine Pending → reines Senden;
  Fehler-Lauf → Pending verworfen.
- `agent:confirm`-Callback: führt alle Pending aus, fasst zusammen; TTL-abgelaufen
  → Hinweis. `agent:cancel` → verwirft.
- Bestehende Suite bleibt grün; Handler-Tests werden mit dem Handler gelöscht/an
  die neue Rückgabeform angepasst.

**Golden-Set (Agenten-Qualität, manuell via Telegram, pro Zyklus):**

- Trivial-schnell: „Wie wird das Wetter morgen?" → ein Tool-Call, schnelle Antwort.
- Mehrschritt: „Schreib X eine Mail dass das Meeting verschoben ist und leg mir
  einen Termin dafür an" → Mail-Write + Kalender-Write, *ein* gebündelter Confirm.
- Disambiguierung: „Lösch die Mail von der Bank" bei 3 Bank-Mails → Agent fragt im
  Text nach oder wählt; Confirm zeigt konkretes Ziel.
- Code-Frage: „Was steht im Backlog von immo-radar?" → `coding` query.
- Regressions-Basislinie: strukturierte Aufgaben nicht messbar langsamer/schlechter
  — Latenz pro Zyklus notieren.

**Erfolgskriterien:** alle 8 Intents agentisch · gebündelter Write-Confirm
funktioniert über Tool-Grenzen hinweg · keine Routing-Fehler-Meldungen für
konvertierte Intents erreichbar · keine Downtime · bestehende Suite grün.

## Restpunkte für den Umsetzungsplan

- **Agent-System-Prompt** wächst pro Zyklus: jedes neue Tool + der Hinweis
  „Write-Aktionen werden vorgemerkt, nie ohne Confirm ausgeführt — sag Philipp, was
  du vorbereitet hast" (damit der Agent seine Antwort richtig formuliert).
- **`_MAX_TURNS=12`** und **Kontext-Budget** (9 Tool-Definitionen + System-Prompt +
  Memory + Profil + History) nach jedem Zyklus beobachten — Tool-Beschreibungen
  knapp halten, nicht spekulativ optimieren.
- Genaues Schema je Tool (Aktionen, Parameter) — der Umsetzungsplan leitet es aus
  den heutigen Handlern / Unter-Agenten ab.

## Bewusst nicht im Scope (YAGNI)

- **Router-Entfall** — das ist Phase 3.
- **Agent-Fortsetzung nach Write-Confirm** — v2.
- **SQLite-Persistenz des Pending-Stores** — ein 3-Minuten-Confirm braucht das nicht.
- **Modell-Tiering** — erst wenn Latenz real nervt.
- **Auswahl-InlineKeyboard bei Mehrdeutigkeit** — entfällt; der Agent disambiguiert
  im Text, der Write-Confirm fängt falsche Picks ab.
