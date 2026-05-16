# Spec: Code-Gesundheit Phase 2 — `main.py`-Split

**Datum:** 2026-05-16
**Status:** Design — freigegeben, Plan ausstehend
**Projekt:** herrlich-ai-platform (Jarvis)

---

## Kontext & Ziel

`agents/main.py` ist auf ~1784 Zeilen gewachsen und vermischt sechs
Verantwortlichkeiten: FastAPI-Routen, Telegram-Handler, den Intent-Dispatcher
`_process_text` (~372 Zeilen), die Mail-/Kalender-Domänen-Handler, `handle_callback`
(~220 Zeilen) und das Lifecycle/Scheduler-Setup. Phase 1 hat ein Charakterisierungs-
Testnetz um die kritischen Pfade gelegt. Phase 2 nutzt dieses Netz, um `main.py`
in zehn fokussierte Module aufzuteilen und `_process_text` in saubere
per-Intent-Handler zu zerlegen.

Kein anderes Modul importiert aus `main.py` — es ist reiner Entry-Point. Das senkt
das Risiko: nur die Testdateien sind externe Konsumenten von `main.py`-Symbolen.

## Nicht-Ziele

- **Kein Verhaltens-Umbau.** Phase 2 ist verhaltensneutral. Jede Funktion behält
  ihre Logik; es ändern sich nur Dateiort, Import-Zeilen und (einmalig) die
  Referenznamen des geteilten States.
- **Keine neuen Features, keine Bugfixes** außer dem, was die Zerlegung erzwingt.
- **`_process_text`-Zerlegung ist Move-only** — jeder `if intent ==`-Branch wird
  1:1 zu einer Handler-Funktion, der Rumpf bleibt unverändert.

---

## Leitprinzipien

### 1. „Zerlegen" und „Verschieben" sind getrennte Schritte

Das Logik-Risiko (`_process_text` zerlegen) wird auf **genau einen Task** isoliert
und **vor jedem Datei-Move** erledigt. `_process_text` wird zuerst *in place*
zerlegt — alle `handle_<intent>`-Funktionen entstehen, bleiben aber vorerst in
`main.py`. Das Testnetz beweist die Verhaltensneutralität. Erst danach beginnen
die Datei-Moves, und die sind dann reine, trivial verifizierbare Relocations.

### 2. Move-only als überprüfbare Disziplin

Bei jedem Move-Task gilt: **Funktionsrümpfe byte-identisch** — es ändern sich nur
Dateiort und Import-Zeilen. Der Diff eines Move-Tasks MUSS als „reine
Verschiebung" lesbar sein. Das ist das explizite Verifikations-Kriterium für
Spec- und Code-Review jedes Move-Tasks.

### 3. Inkrementell — Suite nach jedem Task grün

Ein Modul pro Task: Modul extrahieren → betroffene Test-Importe nachziehen →
komplette Suite grün → Commit. `main.py` ist nach jedem Task lauffähig.

---

## Geteilter State — `app_state.py`

Der Knackpunkt: 5 mutable Dicts plus 3 lazy-initialisierte Agenten werden quer
durch `main.py` gelesen/geschrieben. Lösung: ein **`app_state.py`-Modul**, das
allen geteilten State hält; alle Konsumenten greifen via `app_state.<name>` zu.

`app_state.py` enthält:
- `pending_mail_ops`, `pending_calendar_ops`, `last_mail_search`,
  `last_calendar_search` (dicts), `processed_updates` (set)
- `memory_agent`, `conversation_db`, `profile_agent` (None-initialisiert,
  von `startup()` gesetzt)
- `_PENDING_OP_TTL` + `_pending_op_expired()` (state-nah)

**`app_state.py` bleibt import-arm** — es hält nur State-Werte und importiert
keine Agenten-Klassen. `startup()` importiert `MemoryAgent` etc. und weist zu
(`app_state.memory_agent = MemoryAgent(...)`). Damit kein Zyklus-Risiko.

Beim Anlegen von `app_state.py` werden in einem Zug **alle Referenzen in der noch
monolithischen `main.py` umbenannt** (`_pending_mail_ops` → `app_state.pending_mail_ops`
usw.). Danach tragen alle folgenden Modul-Moves bereits korrekten Code.

Der `calendar_agent`-Singleton (`CalendarAgent()`) zieht mit `calendar_handler.py`
um (einziger Nutzer).

---

## Ziel-Modulstruktur (10 Module)

```
main.py            FastAPI-App, bot_app, Routen (telegram/health/oauth),
                   startup, shutdown, Scheduler-Setup
app_state.py       geteilter State + TTL-Helper (import-arm)
formatting.py      reine Formatter: format_calendar_response, format_mail_list,
                   format_folder_list, _fmt_*, _md_safe, _WEEKDAYS_DE
dispatch.py        _process_text (schlanker Orchestrator), handle_message,
                   handle_voice, start, _conv_*-Helfer, send_typing/_keep_typing
mail_handler.py    handle_mail, _handle_mail_write, _show_mail_action_confirm
calendar_handler.py  handle_calendar, handle_calendar_modify,
                   _show_calendar_action_confirm, detect_calendar_window,
                   calendar_agent-Singleton
chat_handler.py    ask_claude + handle_personal/handle_work/handle_research
intent_handlers.py handle_coding, handle_tasks, handle_news, handle_weather,
                   handle_briefing, handle_reminder_write, handle_memory,
                   send_briefing (Scheduler-Job)
callbacks.py       handle_callback
github_webhook.py  github_webhook + _GITHUB_REPOS
```

Abhängigkeiten fließen **eine Richtung**:
`main → dispatch/callbacks → handler-Module → app_state/formatting`.
Handler rufen nie in `dispatch` zurück → keine Import-Zyklen.

Module landen bei ~130–270 Zeilen. `conversation`-Helfer (`_conv_*`, ~50 Zeilen)
bekommen kein eigenes Modul — sie nutzt ausschließlich `_process_text` und ziehen
mit nach `dispatch.py`.

---

## `_process_text`-Zerlegung

`_process_text(text, chat_id, update)` bleibt der **Orchestrator** in `dispatch.py`:

1. `route_with_llm` aufrufen
2. `memory_context` + `history` laden (für `personal`/`work`/`research`)
3. an `handle_<intent>(...)` dispatchen
4. `history` speichern + Profil aktualisieren (für `personal`/`work`/`research`)

Jeder `if intent ==`-Branch wird **1:1** eine `handle_<intent>`-Funktion im
passenden Handler-Modul (Rumpf unverändert).

**Handler-Schnittstelle** — die einzige nicht-rein-mechanische Stelle der
Zerlegung. Sie wird im Plan pro Handler exakt festgelegt, nach dem Prinzip:
*jeder Handler bekommt genau die Variablen als Parameter, die sein Branch heute
aus dem `_process_text`-Scope liest.*
- Schlanke Intents (`news`, `weather`, `tasks`, `briefing`, `reminder_write`,
  `coding`, `memory`): `handle_<intent>(chat_id, text, params, update)`,
  Rückgabe `None`.
- Chat-Intents (`personal`, `work`, `research`): zusätzlich `memory_context`
  und `history` als Parameter; sie **geben die Antwort zurück**, damit der
  Orchestrator History/Profil speichern kann.

Die gemeinsame Vor-/Nachlogik (Routing, Memory/History-Laden und -Speichern)
bleibt im Orchestrator — sie wird **nicht** in die Handler dupliziert.

---

## Sequenzierung

1. **Testnetz vervollständigen** — `_process_text`-Dispatch-Tests für alle Intents,
   die heute keinen haben (`mail`, `research`, `coding`, `tasks`, `news`,
   `weather`, `briefing`, `reminder_write`, `work`). Kein Code-Move, nur Tests.
   Diese Tests treffen `handle_message`→`_process_text` und überleben die
   Zerlegung unverändert — sie sind ihr Verifikat.
2. **`_process_text` *in place* zerlegen** — einziger Logik-Risiko-Task. Alle
   `handle_<intent>`-Funktionen entstehen in `main.py`, `_process_text` wird
   Orchestrator. Suite grün beweist Verhaltensneutralität.
3. **`app_state.py`** anlegen + alle State-Referenzen in `main.py` umbenennen.
4. **`formatting.py`**, **`github_webhook.py`** extrahieren (Blätter, risikolos).
5. **`mail_handler.py`**, **`calendar_handler.py`**, **`chat_handler.py`**,
   **`intent_handlers.py`** extrahieren — je ein Task, reine Relocation.
6. **`callbacks.py`** extrahieren.
7. **`dispatch.py`** extrahieren (Orchestrator + `handle_message/voice/start` +
   `_conv_*` + Typing-Helfer).
8. `main.py` final prüfen + Deploy.

Ab Task 3 ist jeder Task eine beweisbar verhaltensneutrale Relocation.

---

## Tests

- **Task 1** ergänzt `_process_text`-Dispatch-Tests (vermutlich neue Datei
  `tests/test_dispatch_main.py` oder Erweiterung von `test_chat_quality_main.py`/
  `test_main_memory.py`) — Muster wie bestehend: gemockter Bot, `route_with_llm`
  gepatcht, je Intent geprüft dass der richtige Downstream-Agent/Handler läuft.
- **Jeder Move-Task aktualisiert die betroffenen Test-Importe.** Die Phase-1-
  Testdateien (`test_callback_main.py`, `test_github_webhook.py`) und die
  bestehenden `test_*_main.py` importieren `agents.main`-Symbole bzw. patchen
  `agents.main.<x>`. Wenn ein Symbol umzieht, müssen Importe und Patch-Ziele in
  lockstep nachgezogen werden (z.B. `agents.main.calendar_agent` →
  `agents.calendar_handler.calendar_agent`, `agents.main._pending_mail_ops` →
  `agents.app_state.pending_mail_ops`).
- Erfolgskriterium pro Task: komplette Suite grün (`PYTHONPATH=agents pytest`,
  ohne die drei Live-API-Dateien).

---

## Risiken & offene Punkte

- **`startup()` verdrahtet `bot_app`** mit `handle_message`/`handle_voice`/`start`/
  `handle_callback`. Nach den Moves importiert `startup()` (in `main.py`) diese aus
  `dispatch.py`/`callbacks.py`. `bot_app` selbst bleibt in `main.py` — `conftest.py`
  mockt `telegram.ext.Application.builder` weiterhin korrekt.
- **Import-Zyklen** — werden durch die Einbahn-Abhängigkeit (main → dispatch/
  callbacks → handler → app_state/formatting) und das import-arme `app_state.py`
  vermieden. Jeder Move-Task prüft den Import von `agents.main` als Smoke-Test.
- **Funktionslokale Importe** in `handle_callback`/Handlern (`from mail_agent import
  MailAgent` etc.) ziehen unverändert mit um — sie bleiben funktionslokal,
  Move-only.
- **Plan-Umfang** — ~13 Tasks. Jeder einzeln klein und isoliert; die Größe liegt
  in der Anzahl, nicht in der Komplexität einzelner Tasks.
