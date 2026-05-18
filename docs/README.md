# Doku-Modell

Drei Doku-Arten, je **eine** Quelle der Wahrheit, getrennt nach Zeitform:

| Zeitform | Doc | Rolle |
|---|---|---|
| Gegenwart | `CLAUDE.md` (Root) | Wie Jarvis **jetzt** ist: Architektur, Konventionen, Deploy. Beschreibt nie Geplantes. |
| Zukunft | `BACKLOG.md` (Root) | SSoT für **offene** Entwicklung: jedes Vorhaben als priorisierter Eintrag. Beschreibt nie den Ist-Zustand. |
| Vergangenheit | `docs/plans/done/` | Archiv abgeschlossener Pläne. |

`docs/plans/` (ohne `done/`) enthält die **aktiven** Design-/Umsetzungspläne.

## Lebenszyklus eines Vorhabens

1. Idee → kurzer Eintrag in `BACKLOG.md`.
2. Wird ernst → Design-/Umsetzungsplan in `docs/plans/`; der BACKLOG-Eintrag verlinkt ihn.
3. Fertig → `CLAUDE.md` auf die neue Realität aktualisiert · BACKLOG-Eintrag raus · Plan nach `docs/plans/done/`.

So zeigt `docs/plans/` immer auf einen Blick, was *läuft*, und `BACKLOG.md` ist die vollständige Liste des Offenen.

## Betriebs-Doku

Setup-/Betriebsanleitungen liegen direkt in `docs/` (`setup-vps.md`, `mac-setup.md`) — kein Lebenszyklus, einfach aktuell halten.
