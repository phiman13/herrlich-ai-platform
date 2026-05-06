# tests/test_router_context.py
import pytest
import time
from unittest.mock import patch, MagicMock, AsyncMock


@pytest.mark.asyncio
async def test_get_calendar_names_reads_env():
    with patch.dict("os.environ", {"CALENDAR_WHITELIST": "Privat, Arbeit, Sport"}):
        import importlib
        import agents.router as router_mod
        router_mod._calendar_names_cache = []  # reset cache
        names = await router_mod._get_calendar_names()
    assert "Privat" in names
    assert "Arbeit" in names
    assert "Sport" in names


@pytest.mark.asyncio
async def test_get_mail_folder_names_returns_cached():
    import agents.router as router_mod
    router_mod._mail_folders_cache = (["Posteingang", "Steuern"], time.time())
    names = await router_mod._get_mail_folder_names()
    assert "Posteingang" in names
    assert "Steuern" in names


@pytest.mark.asyncio
async def test_build_system_prompt_includes_calendar_and_mail():
    import agents.router as router_mod
    with patch.object(router_mod, "_get_project_list", new_callable=AsyncMock, return_value=["recipe-app"]), \
         patch.object(router_mod, "_get_todo_list_names", new_callable=AsyncMock, return_value=["Einkaufen"]), \
         patch.object(router_mod, "_get_calendar_names", new_callable=AsyncMock, return_value=["Privat"]), \
         patch.object(router_mod, "_get_mail_folder_names", new_callable=AsyncMock, return_value=["Steuern"]):
        prompt = await router_mod._build_system_prompt()
    assert "Privat" in prompt
    assert "Steuern" in prompt
