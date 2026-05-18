# Agentischer Jarvis — Design

**Status:** Design — freigegeben 2026-05-18
**Umsetzung:** ab sofort — Bau gestartet 2026-05-18 (siehe Rollout) · Backlog: P1 in `BACKLOG.md`
**Verwandt:** Agent-SDK-Migration (P2, verschmilzt hiermit) · Second Brain (P2) · Code-Index (P3, entfällt — siehe YAGNI)

## Ziel

Gespräche mit Jarvis sollen sich so intelligent anfühlen wie ein Chat mit Claude direkt. Der Engpass ist nicht das Modell, sondern die Architektur: die Konversations-Intents (`personal`/`work`/`research`) sind heute Single-shot-`messages.create()`-Aufrufe hinter einem Haiku-Router — kein Werkzeug-Zugriff, kein Iterieren, kein Code-/Datei-Kontext. Lösung: der Gesprächspfad wird ein echter Agent mit Werkzeugen, Kontext und Denk-Schleife.

## Kernentscheidungen

| Thema | Wahl | Begründung |
|---|---|---|
| **Scope** | Hybrid — der Agent als „Fronttür" | Einfache, klare Anfragen laufen weiter schnell & deterministisch über die Handler (als Tools); komplex/gesprächig wird der Agent selbst agentisch. Beseitigt nebenbei den Router-Fehlmodus Fehlklassifikation. |
| **Fundament** | Claude Agent SDK | Bringt Agenten-Loop, Tool-Use, Kontext-Management mit. Verschmilzt mit der ohnehin geplanten Agent-SDK-Migration (ein Umbau statt zwei). Das Abo-Guthaben deckt den token-hungrigen Loop. |
| **Reichweite v1** | Stufe 1: Handler-Tools + Datei-/Code-Lesen + Web | Schließt schon den Großteil der Lücke. Ein Agent mit Datei-Tool exploriert selbst — macht ein separates RAG-Subsystem überflüssig. |
| **Modell** | Sonnet 4.6, per Config auf Opus umstellbar | Der Architektur-Umbau (Single-shot → Agent) ist ~80 % des „fühlt sich klüger an"-Gewinns, nicht das Modell. Sonnet hält Latenz & Kosten angenehm. |

## Constraints

- **Keine Downtime.** Jarvis bleibt durchgehend nutzbar, auch während des Umbaus. Additiv, kein Big-Bang.
- **Kosten.** Der agentische Loop ist token-hungrig → Produktivbetrieb auf dem Agent-SDK-Abo-Guthaben, nicht Pay-as-you-go.
- **Telegram.** Längere Antwortzeiten (~3–15 s) sind akzeptabel, durch den Typing-Indikator abgedeckt.

## Architektur

**Heute:** `Telegram → main.py → router.py (Haiku klassifiziert Intent) → fester Handler`.

**Ziel:** `Telegram → der Agent`. Ein Agent (Sonnet 4.6, Claude Agent SDK) ist die einzige Fronttür. Er bekommt jede Nachricht + Gesprächsverlauf + Memory + Profil und verfügt über Werkzeuge (siehe unten). Triviale, klare Anfrage → ein Tool-Call, fertige Antwort. Komplex/gesprächig → er denkt, ruft mehrere Tools, iteriert.

`router.py` entfällt — die Intent-Klassifikation *ist* dann „der Agent wählt ein Werkzeug" (Entfall am Ende des Rollouts, siehe Rollout).

**Bewusste Vereinfachung:** ein Agent mit ~9 Werkzeugen, keine Sub-Agenten/Orchestrator — für einen Single-User-Assistenten Over-Engineering.

**Latenz:** triviale Anfragen kosten künftig ~2 Modell-Roundtrips statt 1 (Haiku-Routing entfällt, dafür Agenten-Loop). Für v1 bewusst akzeptiert; messen, nur bei realem Bedarf später optimieren (Modell-Tiering) — kein spekulatives Vor-Optimieren.

## Werkzeuge & Sicherheitsmodell

**Tool-Muster.** Ein Werkzeug nimmt typisierte Parameter und gibt ein **strukturiertes Ergebnis** zurück — inklusive strukturierter Fehler (z. B. „Mail-Suche fehlgeschlagen: Token abgelaufen"), damit der Agent reagieren kann statt abzubrechen. Keine direkten Telegram-Seiteneffekte mehr; der Agent formuliert die Antwort. Die heutigen Handler reden direkt mit Telegram — sie werden zu solchen Rückgabe-Funktionen umgebaut (echtes Refactoring, ein Handler nach dem anderen).

**Granularität.** ~9 *fähigkeits*-Tools statt vieler Mikro-Tools — `mail`, `calendar`, `tasks`, `weather`, `news`, `briefing`, `workspace` (Datei lesen/suchen), `web`, `coding` — jedes mit Aktions-Parameter. Weniger Tools = treffsicherere Tool-Wahl, kleinerer Prompt.

**Zwei Aktions-Klassen:**
- **Lese-Aktionen** — laufen frei, ohne Rückfrage.
- **Schreib-/destruktive Aktionen** — Human-in-the-Loop.

Ein Permission-Hook des Agent SDK prüft die *Aktion* im Tool-Input: `read` → auto-erlaubt, `send`/`delete`/… → Confirm.

**Write-Confirm-Fluss.** Schreib-Aktionen führen *nicht* direkt aus — sie merken eine Aktion vor und geben „vorgemerkt" an den Agenten zurück. Der Agent läuft normal weiter und kann mehrere Aktionen sammeln. Am Lauf-Ende: *ein* gebündelter Telegram-Confirm (InlineKeyboard, z. B. „1) Mail an X, 2) Termin Y — bestätigen?"). Der Confirm-Callback führt die vorgemerkten Aktionen aus — ohne den Agenten fortzusetzen. Restart-fest (nutzt das heutige `_pending_*`-Muster). Den Agenten nach dem Confirm fortzusetzen ist mögliches v2.

`claude-guard` bleibt zusätzlich für das `coding`-Tool aktiv. Die heutigen `*:action:confirm`-Callbacks (Mail/Kalender) verallgemeinern sich zu *einer* generischen Tool-Bestätigung — weniger Spezialcode.

## Datenfluss & Bestandsaufnahme

**Pro Telegram-Nachricht:**
1. Nachricht → `dispatch.py` (dünn: Voice→Transkript, dann an den Agenten übergeben).
2. Kontext laden: Gesprächsverlauf (`ConversationDB`), Memory (`MemoryAgent`), Profil (`ProfileAgent`).
3. Agentenlauf (Agent SDK, Sonnet) mit dem Tool-Set — ein frischer Lauf pro Nachricht, History wird reingereicht; keine dauerhaft offene Session → restart-fest.
4. Typing-Indikator während des Laufs.
5. Antwort → Telegram · finale user/assistant-Turns in `ConversationDB` · Memory-Extraktion async.

**History-Schema:** persistiert werden nur die *finalen* user/assistant-Text-Turns — **nicht** die Tool-Transkripte eines Laufs. Reicht als Cross-Message-Gedächtnis, hält DB und Kontext schlank.

**Kontext-Budget:** System-Prompt + Tool-Definitionen + Memory + Profil + History summieren sich. History knapper fassen (~15 Turns) und die Compaction des Agent SDK im Loop nutzen.

**Nebenläufigkeit:** ein agentischer Lauf dauert länger als die heutigen Handler — eine zweite Nachricht während eines laufenden Laufs wird pro Chat serialisiert (gequeued).

**Bleibt unverändert:** `ConversationDB`, `MemoryAgent`, `ProfileAgent` · proaktive APScheduler-Jobs (Briefing, Mail-Check, Task-Reminder, Weekly-Review, `workspace_sync`) — bleiben deterministisch, die agentische Umstellung betrifft nur die Konversations-Fronttür · GitHub-Webhook/Auto-Deploy · Voice-Transkription · die MS-Graph-/Wetter-/News-Agenten (liefern den Tools zu).

**Geht/ändert sich:** `router.py` entfällt (am Rollout-Ende) · `dispatch.py` schrumpft auf „Nachricht → Agent" · `intent_handlers.py` / `*_handler.py` → Tool-Funktionen · `callbacks.py` → generische Tool-Bestätigung.

## Rollout

Additiv, kein Big-Bang, Jarvis durchgehend nutzbar. **Feature-Flag** (Env-Schalter): aus = heutiger Pfad, an = Agenten-Pfad. Der neue Pfad wird hinter dem Flag gebaut und getestet; Umschalten erst wenn er steht, Rückschalten jederzeit möglich.

**Drei Phasen** — jede ein lauffähiger Zustand:

- **Phase 1 — Fundament + Konversation.** Agent-SDK-Migration, Agenten-Loop, Tools `workspace` + `web`. Der Agent übernimmt zunächst nur `personal`/`work`/`research` (heute ohnehin Single-shot → einfachster, wertvollster Einstieg). Der Router bleibt vorerst und routet strukturierte Intents wie gehabt.
- **Phase 2 — Handler → Tools.** Die strukturierten Handler werden einzeln zu Tools. Reihenfolge nach Risiko: zuerst ein Read-only-Pilot (`weather` oder `news`) — beweist das Tool-Muster ohne Confirm-Komplexität — dann `tasks`/`briefing`, die schreib-lastigen `mail`/`calendar` zuletzt, `coding` separat (Guard). Jede Konvertierung ist ein eigener Mini-Zyklus (Refactor → Test → Deploy) und git-revertierbar.
- **Phase 3 — Router raus.** Sind alle Handler Tools, entfällt `router.py`; der Agent ist alleinige Fronttür = Ziel-Architektur.

Der Router ist also nicht Tag-1-weg, sondern das transitionale Gerüst — er retiriert am Ende.

**Timing:** Kein Gate — die Umsetzung beginnt sofort (2026-05-18). Das Agent SDK läuft bereits heute auf dem normalen Monats-Budget des Claude-Abos (kein Pay-as-you-go). Am 15.06.2026 kommt lediglich ein *separates Zusatzbudget* für Agent-SDK-Apps dazu, das das normale Budget entlastet — eine Kostenentlastung, kein Startdatum.

## Test & Erfolgskriterien

- **Basislinie:** die bestehende Test-Suite bleibt grün.
- **Pro konvertiertem Handler:** dessen Tests an die neue Rückgabe-Form anpassen.
- **Neue Unit-Tests** für die deterministischen Teile: Tool-Permission-Hook (Lesen frei / Schreiben Confirm), History-Wiring, der Vormerk-/Confirm-Mechanismus.
- **Agenten-Qualität** (nicht unit-testbar): ein **Golden-Set realer Szenarien** pro Phase, die nachweislich laufen müssen — z. B. Frage zu einem Detail aus Projekt-Code, Mehrschritt-Anfrage (Mail + Termin in einem), trivialer schneller Fall (Wetter). Plus **Regressions-Basislinie:** strukturierte Aufgaben dürfen messbar nicht langsamer/schlechter werden.
- Golden-Path je Phase manuell über Telegram, abgesichert durchs Feature-Flag.

**Erfolgskriterien:** Gespräche so intelligent wie mit Claude direkt · der Agent beantwortet fundiert Fragen zu Projekten/Code · Mehrschritt-Anfragen in einem Rutsch · keine „Routing-Fehler"-Meldungen mehr · strukturierte Aufgaben (Wetter, Erinnerung) weiter schnell & verlässlich · keine Downtime.

## Bewusst nicht im Scope (YAGNI)

- **Sub-Agenten / Orchestrator** — ein Agent reicht für einen Single-User.
- **Modell-Tiering** im Loop — erst wenn Latenz real nervt.
- **Code-Index / RAG** (Backlog-Idee „B") — entfällt: ein Agent mit Datei-Tool exploriert selbst.
- **Second Brain** (Backlog P2) — eigener Layer *nach* v1 (entspräche „Stufe 2").
- **„Stufe 3"** (Agent legt eigene Werkzeuge an, handelt proaktiv) — nach Live-Erfahrung mit v1.
- **Agentische proaktive Jobs** — die Scheduler-Jobs bleiben deterministisch.
- **Agent-Fortsetzung nach Write-Confirm** — v2.

## Offene Punkte für den Umsetzungsplan

- Konkretes Agent-SDK-Setup: OAuth-Auth statt `ANTHROPIC_API_KEY`, Session-Handling, Compaction-Konfiguration.
- Genaues Schema je der ~9 Werkzeuge (Parameter, Aktionen, Rückgabeformat).
- Exakte Reihenfolge + Aufwandsschätzung der Phase-2-Handler-Konvertierungen.
- Konkretes Golden-Set an Test-Szenarien.
- System-Prompt des Agenten (Rolle, Stil, Werkzeug-Hinweise, Wann-nachfragen).
