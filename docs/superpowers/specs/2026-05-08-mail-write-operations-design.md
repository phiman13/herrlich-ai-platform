# MS Graph Mail Write Operations — Design Spec

**Goal:** Erweitert den bestehenden Mail-Agenten um Schreiboperationen (Archivieren, Verschieben, Löschen, Als gelesen/ungelesen markieren, Antworten, Weiterleiten) mit Smart-Search-basierter Mail-Identifikation und Bestätigungs-Dialogen für destruktive Operationen.

**Datum:** 2026-05-08

---

## Architektur

Drei bestehende Dateien werden geändert. Keine neuen Dateien.

| Datei | Änderung |
|---|---|
| `agents/mail_agent.py` | 7 neue Methoden für MS Graph Write-Endpoints |
| `agents/router.py` | 6 neue Mail-Modes, neue Parameter |
| `agents/main.py` | Unified pending state, multi-result flow, neue Callbacks |

---

## 1. mail_agent.py — Neue Methoden

### `get_mail_body(mail_id: str) -> dict`
Holt Volltext einer Mail vor Reply/Forward-Bestätigung.

```
GET /me/messages/{id}?$select=id,subject,from,receivedDateTime,body
```

Gibt `{"id", "subject", "sender_name", "sender_email", "received", "body_text"}` zurück. `body_text` ist der HTML-stripped Plaintext (max. 500 Zeichen für Preview).

### `mark_read(mail_id: str, is_read: bool = True) -> bool`
```
PATCH /me/messages/{id}
Body: {"isRead": true|false}
```
Kein Confirm-Dialog nötig (trivial reversibel). Gibt `True` bei 200.

### `archive(mail_id: str) -> bool`
```
POST /me/messages/{id}/archive
```
Gibt `True` bei 200.

### `move(mail_id: str, destination_folder_id: str) -> bool`
```
POST /me/messages/{id}/move
Body: {"destinationId": "<folder_id>"}
```
Gibt `True` bei 200.

### `delete(mail_id: str) -> bool`
```
DELETE /me/messages/{id}
```
Verschiebt in Papierkorb (DeletedItems), nicht permanent. Gibt `True` bei 204.

### `reply(mail_id: str, comment: str) -> bool`
```
POST /me/messages/{id}/reply
Body: {"comment": "<comment>"}
```
Gibt `True` bei 202.

### `forward(mail_id: str, to_emails: list[str], comment: str = "") -> bool`
```
POST /me/messages/{id}/forward
Body: {"toRecipients": [{"emailAddress": {"address": "..."}}], "comment": "<comment>"}
```
Gibt `True` bei 202.

---

## 2. router.py — Erweiterungen

### Neue Modes im Mail-Intent

```
mark_read    — "Markiere die Mail von X als gelesen"
mark_unread  — "Markiere als ungelesen"
archive      — "Archiviere die Mail von X"
move         — "Verschiebe die Mail von X in den Ordner Y"
delete       — "Lösche die Mail von X"
reply        — "Antworte auf die Mail von X: <Text>"
forward      — "Leite die Mail von X weiter an y@example.com"
```

### Neue Parameter

| Parameter | Typ | Beschreibung |
|---|---|---|
| `mail_query` | string oder null | Freitext-Beschreibung der Zielmail (z.B. "letzte Mail von Sparkasse") |
| `reply_text` | string oder null | Antworttext, nur bei mode=reply |
| `forward_to` | string oder null | Empfängeradresse, nur bei mode=forward |
| `forward_text` | string oder null | Begleittext, nur bei mode=forward, optional |
| `destination_folder` | string oder null | Ordnername, nur bei mode=move |

### Router-Prompt Anpassung

Den Satz `"NUR LESEN, keine Aktionen wie verschieben oder löschen. Außer mode=compose."` durch die neuen Modes ersetzen. Für `mail_query` soll der Router alles extrahieren was die Mail identifiziert: Absender, Betreff-Keywords, Zeit.

Beispiel-Mappings:
- "Markiere die Sparkasse-Mail als gelesen" → `mark_read`, `mail_query="Mail von Sparkasse"`
- "Archiviere die letzte Mail von Anna" → `archive`, `mail_query="letzte Mail von Anna"`
- "Antworte auf die Mail über das Meeting mit: Passt mir gut" → `reply`, `mail_query="Mail über Meeting"`, `reply_text="Passt mir gut"`
- "Leite die Rechnung von Müller weiter an chef@firma.de" → `forward`, `mail_query="Rechnung von Müller"`, `forward_to="chef@firma.de"`

---

## 3. main.py — Änderungen

### Unified Pending State

`_pending_mail_drafts` wird zu `_pending_mail_ops: dict[int, dict]` erweitert (bestehende Compose-Logik bleibt, nur umbenannt). Jeder Eintrag hat ein `type`-Feld:

```python
_pending_mail_ops: dict[int, dict] = {}
# Beispiel Eintrag:
{
  "type": "archive",       # compose | archive | move | delete | reply | forward
  "mail_id": "AAMk...",
  "subject": "Kontoauszug März",
  "sender": "Sparkasse",
  # Compose-spezifisch:
  "to_email": "...",        # nur type=compose
  "body": "...",            # nur type=compose
  # Reply/Forward-spezifisch:
  "reply_text": "...",      # nur type=reply
  "forward_to": "...",      # nur type=forward
  # Move-spezifisch:
  "destination_folder_id": "...",  # nur type=move
}
```

### Multi-Result State mit TTL

```python
_last_mail_search: dict[int, dict] = {}
# Eintrag:
{
  "mails": [...],        # Liste von Mail-Objekten
  "action": "archive",
  "params": {...},
  "timestamp": 1234567890.0  # time.time() beim Speichern
}
```

TTL: 3 Minuten. Beim Lesen prüfen: `if time.time() - entry["timestamp"] > 180: del _last_mail_search[chat_id]`.

### Flow für Write-Operationen

```
handle_mail(mode=write_op):
  1. smart_search(mail_query, n=50) aufrufen
  2. Ergebnisse filtern:
     - 0 Treffer → "Keine passende Mail gefunden für '[query]'."
     - >5 Treffer → "Zu viele Treffer — bitte genauer beschreiben (Absender, Betreff, Datum)."
     - 1 Treffer → direkt zu Schritt 3
     - 2–5 Treffer → nummerierte Auswahlliste mit InlineKeyboard-Buttons, in _last_mail_search speichern, return
  3. Für mark_read/mark_unread: direkt ausführen, kein Confirm-Dialog
  4. Für alle anderen: Confirm-Dialog anzeigen
```

### Confirm-Dialog Format

**Archivieren / Löschen / Verschieben:**
```
🗑️ Mail löschen?

Von: Sparkasse
Betreff: Kontoauszug März
Datum: 27.04. 09:14

[✅ Ja, löschen]  [❌ Abbrechen]
```

**Reply:**
Vorher `get_mail_body()` aufrufen für Preview.
```
↩️ Antwort auf:
Von: Anna Müller
Betreff: Meeting nächste Woche

Deine Antwort:
"Passt mir gut, bin dabei."

[✅ Senden]  [❌ Abbrechen]
```

**Forward:**
```
↪️ Weiterleiten an: chef@firma.de
Betreff: Rechnung von Müller

[Begleittext falls angegeben]

[✅ Senden]  [❌ Abbrechen]
```

### Neue Callback-Daten

| Callback | Aktion |
|---|---|
| `mail:action:confirm` | Führe pending action aus |
| `mail:action:cancel` | Verwerfe pending action |
| `mail:select:{n}` | Wähle Mail n aus _last_mail_search aus → Confirm-Dialog |

Bestehende Callbacks `mail:send` und `mail:cancel` (für Compose) bleiben unverändert.

---

## 4. Error Handling

| Situation | Verhalten |
|---|---|
| 0 Suchtreffer | "Keine passende Mail gefunden für '[query]'." |
| >5 Suchtreffer | "Zu viele Treffer — bitte genauer beschreiben." |
| Ordner nicht gefunden (move) | "Ordner '[name]' nicht gefunden. Verfügbare: [liste]" |
| Graph API Fehler | "❌ Aktion fehlgeschlagen: [http status]" |
| Pending state abgelaufen (>3 min) | "⏱️ Auswahl abgelaufen — bitte nochmal." |

---

## 5. Tests

**Unit-Tests (neue Datei `tests/test_mail_write.py`):**
- `test_mark_read_calls_patch` — mock requests.patch, prüft Payload
- `test_archive_calls_correct_endpoint` — mock requests.post
- `test_delete_calls_delete_endpoint` — mock requests.delete
- `test_move_sends_destination_id` — mock requests.post, prüft Body
- `test_reply_sends_comment` — mock requests.post
- `test_forward_sends_recipients` — mock requests.post

**Live-API-Tests** (in `tests/test_mail_send.py` integrieren, standardmäßig ignoriert):
- Manuell auf dem VPS mit echtem MS-Token ausführen

---

## 6. MS Graph Berechtigungen

Die bestehende OAuth-Konfiguration braucht `Mail.ReadWrite` Scope (bisher nur `Mail.Read`). Prüfen ob Token-Refresh nötig ist nach Scope-Erweiterung.

**Nächster Schritt:** OAuth-Scopes in `microsoft_auth.py` prüfen und ggf. anpassen — das muss vor dem ersten Deploy geschehen.

---

## Nicht in Scope

- Entwürfe speichern (Drafts)
- Spam markieren
- Regeln/Filter erstellen
- Kategorien setzen
