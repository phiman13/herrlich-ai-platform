<!-- Kanon: personal-stack/core/CONVENTIONS.md · zuletzt propagiert: 2026-05-19
     Nicht hier editieren — Änderung am Kanon, dann neu propagieren. -->

# Konventionen — kanonischer Kern

> Universeller Disziplin-Kern für alle Projekt-Repos. Reist als
> `.claude/CONVENTIONS.md` mit jedem Klon. Kanon:
> `personal-stack/core/CONVENTIONS.md`.
>
> Aufnahme-Kriterium: nur Inhalt, der (universell oder klar bedingt) UND stabil
> UND kurz ist.

## Security — nicht verhandelbar

- Niemals Secrets hardcoden — API-Keys, Tokens, Passwörter ausschließlich aus
  Umgebungsvariablen.
- `.env` nie committen — immer `.env.example` mit Platzhaltern pflegen.
- Supabase: RLS auf allen Tabellen; `service_role`-Key nie im Client-Code.
- Claude API: Key nur serverseitig, nie in Browser-Code oder Git.

## Commit-Konvention

- Nach jeder logischen Änderung: `git add -A && git commit && git push`.
- Format: `typ(scope): was und warum`.
- Typen: `feat` · `fix` · `docs` · `refactor` · `test` · `chore`.
- Ein Commit = eine logische Änderung — klein und fokussiert.

## Definition of Done

1. Lokal getestet (golden path + edge cases).
2. Cross-App-Impact geprüft.
3. Relevante Doku aktualisiert (`CLAUDE.md`, `DEVELOPMENT.md`, `README` wo nötig).
4. *(falls TypeScript)* TypeCheck grün: `tsc --noEmit`.
5. *(falls UI-Änderung)* `/audit` + Browser-Test ausgeführt.
   *(Skill-Bezug — A.2 schärft diese Klausel.)*
6. Committed und gepusht.

## Globale Konventionen

- Sprache: Kommentare und Commit-Messages DE oder EN (konsistent pro Projekt),
  Code/Variablen EN.
- Keine unnötigen Kommentare — nur wenn das WHY nicht offensichtlich ist.
- Keine vorausschauenden Abstraktionen — nur bauen, was jetzt gebraucht wird (YAGNI).
- Fehlerbehandlung nur an System-Grenzen (User-Input, externe APIs), nicht intern.
- Tests vor Implementation, wo möglich (TDD).
- *(Tailwind-Projekte)* `cn()` für conditional Klassen — nie raw string
  concatenation.

## Doku-Ablage

- Design-Specs → `docs/specs/`.
- Implementierungspläne → `docs/plans/`.
- Abgelöste Docs → `docs/archive/`.
- Projekt-Backlog & -Status → Linear (nicht als lokale Datei).
- Verzeichnisse lazy anlegen — sie entstehen mit der ersten Datei.

## Telegram-Notifications *(Projekte mit Telegram-Anbindung)*

Kritische Produktions-Fehler und Start/Ende von Long-running-Operations melden;
Format kurz, faktisch, mit Kontext (welches Projekt, was ist passiert).

## Arbeitsweise

- **Briefing-first:** Vor kreativer Arbeit (Feature, Komponente,
  Verhaltensänderung) erst Intent, Anforderungen und Design klären — nicht direkt
  in Code springen.
- **Kontext-Hygiene:** Kontext zwischen Features verdichten, zwischen
  unzusammenhängenden Aufgaben frisch starten; die Kontext-Last beobachten.
- **User-Decision-Pattern:** Entscheidungen, deren Antwort den weiteren Weg
  ändert und die nicht aus dem Repo verifizierbar sind, dem User vorlegen — nicht
  raten. Sonst konventionelle Defaults wählen und weitermachen.
