import asyncio
import importlib
import logging
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch


class _Filter:
    @staticmethod
    def _decorator(*_args, **_kwargs):
        return lambda function: function

    llm_tool = _decorator
    command = _decorator
    on_llm_request = _decorator


class _Request:
    payload = {}

    async def json(self, default=None):
        return self.payload if self.payload is not None else default


class _Context:
    def __init__(self):
        self.routes = []

    def register_web_api(self, route, handler, methods, description):
        self.routes.append((route, handler, methods, description))


def _install_astrbot_stubs():
    astrbot = types.ModuleType("astrbot")
    api = types.ModuleType("astrbot.api")
    event = types.ModuleType("astrbot.api.event")
    star = types.ModuleType("astrbot.api.star")
    web = types.ModuleType("astrbot.api.web")
    api.logger = logging.getLogger("test_meme_wiki")
    event.AstrMessageEvent = object
    event.filter = _Filter()

    class Star:
        def __init__(self, context):
            self.context = context

    star.Context = _Context
    star.Star = Star
    web.request = _Request()
    web.json_response = lambda payload: payload
    web.error_response = lambda message, status_code=400: {
        "error": message,
        "status_code": status_code,
    }
    return {
        "astrbot": astrbot,
        "astrbot.api": api,
        "astrbot.api.event": event,
        "astrbot.api.star": star,
        "astrbot.api.web": web,
    }


class DashboardApiTests(unittest.TestCase):
    def test_routes_list_entries_and_delete_exact_entry(self):
        with patch.dict(sys.modules, _install_astrbot_stubs()):
            sys.modules.pop("main", None)
            main = importlib.import_module("main")
            with tempfile.TemporaryDirectory() as directory:
                data_path = Path(directory) / "wiki.json"
                context = _Context()
                with patch.object(main.MemeWikiPlugin, "_data_path", return_value=data_path):
                    plugin = main.MemeWikiPlugin(context)

                routes = {route: methods for route, _handler, methods, _desc in context.routes}
                self.assertEqual(
                    routes["/astrbot_plugin_meme_wiki/dashboard/memes"],
                    ["GET"],
                )
                self.assertEqual(
                    routes["/astrbot_plugin_meme_wiki/dashboard/memes/delete"],
                    ["POST"],
                )

                plugin.store.upsert("破防", "心理防线被突破")
                result = asyncio.run(plugin.dashboard_list_memes())
                self.assertEqual(result["count"], 1)
                self.assertEqual(result["entries"][0]["term"], "破防")

                main.request.payload = {"term": "破"}
                result = asyncio.run(plugin.dashboard_delete_meme())
                self.assertEqual(result["status_code"], 404)
                self.assertEqual(plugin.store.count(), 1)

                main.request.payload = {"term": "破防"}
                result = asyncio.run(plugin.dashboard_delete_meme())
                self.assertTrue(result["deleted"])
                self.assertEqual(plugin.store.count(), 0)


if __name__ == "__main__":
    unittest.main()
