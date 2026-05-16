# tests/test_router_context.py
import pytest
import time
from unittest.mock import patch, MagicMock, AsyncMock


@pytest.mark.asyncio
async def test_router_has_no_calendar_names_cache():
    """_get_calendar_names and _calendar_names_cache were removed in Outlook migration."""
    import agents.router as router_mod

    assert not hasattr(router_mod, "_get_calendar_names")
    assert not hasattr(router_mod, "_calendar_names_cache")


@pytest.mark.asyncio
async def test_get_mail_folder_names_returns_cached():
    import agents.router as router_mod

    router_mod._mail_folders_cache = (["Posteingang", "Steuern"], time.time())
    names = await router_mod._get_mail_folder_names()
    assert "Posteingang" in names
    assert "Steuern" in names


@pytest.mark.asyncio
async def test_build_system_prompt_includes_outlook_calendar_and_mail():
    import agents.router as router_mod

    with (
        patch.object(
            router_mod,
            "_get_project_list",
            new_callable=AsyncMock,
            return_value=["recipe-app"],
        ),
        patch.object(
            router_mod,
            "_get_todo_list_names",
            new_callable=AsyncMock,
            return_value=["Einkaufen"],
        ),
        patch.object(
            router_mod,
            "_get_mail_folder_names",
            new_callable=AsyncMock,
            return_value=["Steuern"],
        ),
    ):
        prompt = await router_mod._build_system_prompt()
    assert "Outlook-Kalender" in prompt
    assert "Steuern" in prompt


@pytest.mark.asyncio
async def test_low_confidence_triggers_clarification():
    """handle_message sends clarification when confidence < 5."""
    import agents.main as main_mod

    low_confidence_result = {
        "intent": "personal",
        "confidence": 3,
        "params": {},
        "reasoning": "unsure",
    }

    fake_update = MagicMock()
    fake_update.update_id = 9001
    fake_update.message.text = "bla bla foo"
    fake_update.message.chat_id = 12345
    fake_update.message.reply_text = AsyncMock()

    with (
        patch(
            "agents.main.route_with_llm",
            new_callable=AsyncMock,
            return_value=low_confidence_result,
        ),
        patch.object(main_mod, "processed_updates", new=set()),
    ):
        await main_mod.handle_message(fake_update, MagicMock())

    fake_update.message.reply_text.assert_called_once()
    call_text = fake_update.message.reply_text.call_args[0][0]
    assert any(
        kw in call_text.lower()
        for kw in ("nicht sicher", "präzisier", "klär", "genauer")
    )
