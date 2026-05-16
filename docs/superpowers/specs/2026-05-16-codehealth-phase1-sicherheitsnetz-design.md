# Spec: Code-Gesundheit Phase 1 — Sicherheitsnetz

**Datum:** 2026-05-16
**Status:** Design — freigegeben, Plan ausstehend
**Projekt:** herrlich-ai-platform (Jarvis)

---

## Kontext & Ziel

`agents/main.py` ist auf 1759 Zeilen gewachsen und soll in Phase 2 in fokussierte
Module aufgeteilt werden. Bevor dieser riskante Refactor des Produktiv-Gateways
beginnt, braucht es ein Testnetz: die kritischen, zustandsbehafteten Pfade sind
heute **ungetestet** — vor allem `handle_callback` (die Mail-/Kalender-Confirm-
Zustandsmaschinen) und der GitHub-Webhook.

Phase 1 liefert dieses Netz und behebt zugleich einen kleinen, vorab bekannten
Bug (fehlende TTL auf Pending-Ops). Phase 1 ist bewusst **nicht-strukturell** —
es wird kein Code verschoben; das ist Phase 2.

## Nicht-Ziele

- **Kein Code-Refactor / kein Modul-Split** — das ist Phase 2 (eigene Spec).
- **FastAPI-Route-Wrapper** (`/health`, `/webhook/telegram`, `/oauth/*`) — dünne
  Wrapper, geringer Testwert.
- **`startup()`** — komplexe Async-Init-Sequenz, hoher Mock-Aufwand, geringer Wert.
- **Vollständige Pending-Op-Identität** — der TTL behebt „alter Button feuert".
  Die Variante „Op A stagen, Op B stagen, Button A tippen → führt B aus" bräuchte
  eine pro-Op-ID; bleibt als bekannte Restgrenze außen vor.

---

## Teil A — Pending-Ops-TTL-Fix

### Problem

`_pending_mail_ops` und `_pending_calendar_ops` (Dicts `chat_id → op`) haben kein
Ablaufdatum. Ein Confirm-Button, der Stunden später getippt wird, führt die
Aktion immer noch aus — z.B. eine längst überholte „Mail senden"-Bestätigung.

### Fix (nur `agents/main.py`)

- Neue Konstante `_PENDING_OP_TTL = 600` (10 Minuten).
- Beim Staging schreibt jede Pending-Op `"staged_at": time.time()` in ihr Dict.
  **Vier Staging-Stellen:**
  - `handle_mail` — Compose-Entwurf → `_pending_mail_ops`
  - `_show_mail_action_confirm` — Aktions-Op → `_pending_mail_ops`
  - `handle_calendar` (Write-Branch) — `type=create` → `_pending_calendar_ops`
  - `_show_calendar_action_confirm` — `type=update/delete` → `_pending_calendar_ops`
- Neuer Helper:
  ```python
  def _pending_op_expired(op: dict) -> bool:
      return time.time() - op.get("staged_at", 0) > _PENDING_OP_TTL
  ```
  `op.get("staged_at", 0)` → eine Op ohne Timestamp (theoretisch) gilt als abgelaufen.
- **Geprüft in den drei Ausführungs-Callbacks** in `handle_callback`, jeweils
  direkt nach `op = _pending_*_ops.pop(chat_id, None)` und der `None`-Prüfung:
  `mail:send`, `mail:action:confirm`, `cal:action:confirm`.
  Ist `_pending_op_expired(op)` wahr → `edit_message_text("⏱️ Abgelaufen — bitte
  nochmal.")` und `return`, ohne die Agent-Aktion auszuführen.
- Die Cancel-Callbacks (`mail:cancel`, `mail:action:cancel`, `cal:action:cancel`)
  brauchen **keine** Prüfung — eine abgelaufene Op zu verwerfen ist harmlos.
- Das bestehende 180-Sek-TTL der Such-Auswahl (`_last_mail_search`,
  `_last_calendar_search`) bleibt unverändert.

---

## Teil B — Charakterisierungs-Tests

Neue Tests im Stil der bestehenden `main.py`-Tests (`test_chat_quality_main.py`):
`asyncio.run(...)` plus gemockter `Bot` / gemockte Agenten. Sie schreiben das
**aktuelle** Verhalten fest, damit Phase 2 (der Split) ein Regressionsnetz hat.

### `tests/test_callback_main.py` — `handle_callback` vollständig

Pro Callback-`data`-Wert: relevanten State aufsetzen, gemocktes
`update.callback_query` bauen, `handle_callback` aufrufen, Ergebnis prüfen
(richtige Agent-Methode aufgerufen / richtige Nachricht / State korrekt geleert).

**Abgedeckte Branches:**
- `push:<project>` → `vps.git_push` aufgerufen
- `dismiss` → Keyboard entfernt
- `mail:send` → `MailAgent.send_mail` mit dem gestageten Entwurf
- `mail:cancel` → Entwurf verworfen
- `mail:action:confirm` → je Op-Typ (archive / delete / move / reply / forward)
  die passende `MailAgent`-Methode
- `mail:action:cancel` → `_pending_mail_ops` + `_last_mail_search` geleert
- `mail:select:<idx>` → Mail gewählt, Confirm gezeigt; abgelaufene Suche → Hinweis
- `cal:action:confirm` → je Typ create / update / delete der passende
  `calendar_agent`-Aufruf
- `cal:action:cancel` → `_pending_calendar_ops` + `_last_calendar_search` geleert
- `cal:select:<idx>` → Termin gewählt, Confirm gezeigt; abgelaufene Suche → Hinweis

**TTL-Verhalten** (TDD — Test zuerst, dann Teil-A-Fix):
- Pending-Op mit `staged_at` älter als 600 s → `mail:send` / `mail:action:confirm`
  / `cal:action:confirm` antworten mit „Abgelaufen", **kein** Agent-Call.
- Pending-Op innerhalb der TTL → wird normal ausgeführt.

**Stage→Confirm-Roundtrips** (der Integrations-Wert):
- Mail: `_show_mail_action_confirm` aufrufen → prüfen dass `_pending_mail_ops[chat_id]`
  korrekt befüllt ist (inkl. `staged_at`) → `handle_callback` mit
  `mail:action:confirm` → prüfen dass die `MailAgent`-Methode lief.
- Kalender: `handle_calendar` (Write) bzw. `_show_calendar_action_confirm`
  → `_pending_calendar_ops` prüfen → `handle_callback` mit `cal:action:confirm`
  → prüfen dass `calendar_agent.create_event` / `update_event` / `delete_event` lief.

### `tests/test_github_webhook.py` — HMAC-Validierung

`github_webhook` erhält einen FastAPI-`Request`. Test baut einen gemockten
Request (`body()` async, `headers`), `GITHUB_WEBHOOK_SECRET` gepatcht, die
git/rsync/docker-Seiteneffekte gemockt.
- Gültige HMAC-Signatur → Request akzeptiert, Post-Pull-Aktion angestoßen.
- Ungültige Signatur → abgelehnt, keine Seiteneffekte.
- Fehlende Signatur → abgelehnt.

---

## Mock-Strategie

- `Bot` / `update.callback_query` → `MagicMock` mit `AsyncMock`-Methoden
  (`answer`, `edit_message_text`, `edit_message_reply_markup`) — Muster aus
  `test_chat_quality_main.py`.
- `MailAgent` → gepatcht (`mail_agent.MailAgent`); `calendar_agent` ist ein
  Modul-Singleton → dessen Methoden bzw. `agents.main.calendar_agent` patchen.
- `vps.git_push` → gepatcht.
- GitHub-Webhook: `os.environ["GITHUB_WEBHOOK_SECRET"]` gesetzt, die
  Deploy-Funktionen (git/rsync/docker) gepatcht — keine echten Seiteneffekte.
- `staged_at` für TTL-Tests wird im Test direkt gesetzt (z.B. `time.time() - 700`
  für „abgelaufen"), kein Sleep.

---

## Erfolgskriterien

1. `_pending_op_expired` + die `staged_at`-Stempel + die drei Callback-Prüfungen
   implementiert; abgelaufene Confirm-Buttons feuern nicht mehr.
2. `tests/test_callback_main.py` deckt alle `handle_callback`-Branches, das
   TTL-Verhalten und die Mail-/Kalender-Stage→Confirm-Roundtrips ab.
3. `tests/test_github_webhook.py` deckt HMAC gültig / ungültig / fehlend ab.
4. Komplette Test-Suite grün.

## Risiken & offene Punkte

- **Charakterisierungs-Tests können echte Bugs aufdecken.** Falls ein Test das
  aktuelle Verhalten als fehlerhaft entlarvt, wird der Bug gemeldet — nicht
  einbetoniert. Der Plan/die Umsetzung entscheidet dann fallweise.
- **Mock-Tiefe bei `handle_callback`.** Einige Branches importieren Agenten
  funktionslokal (`from mail_agent import MailAgent`). Die Tests müssen am
  richtigen Ort patchen; das wird im Plan pro Branch konkretisiert.
- **`github_webhook`-Seiteneffekte.** Der Test darf keine echten git/docker-
  Kommandos auslösen — alle Deploy-Pfade müssen gemockt sein. Der Plan listet
  die exakten Patch-Punkte.
