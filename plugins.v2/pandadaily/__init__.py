import json
import re
import traceback
from datetime import datetime, timedelta
from html import unescape
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.config import settings
from app.log import logger
from app.plugins import _PluginBase

try:
    from app.schemas.types import NotificationType
except Exception:
    NotificationType = None


class PandaDaily(_PluginBase):
    plugin_name = "PANDA Daily"
    plugin_desc = "Run PANDA friend-trade daily tasks: greeting work, pat interaction, and income claim."
    plugin_icon = "signin.png"
    plugin_version = "1.0.0"
    plugin_author = "Codex"
    author_url = "https://github.com/jxxghp/MoviePilot-Plugins"
    plugin_config_prefix = "pandadaily_"
    plugin_order = 50
    auth_level = 1

    _scheduler: Optional[BackgroundScheduler] = None
    _enabled = False
    _onlyonce = False
    _notify = True
    _cookie = ""
    _cron = "0 7 * * *"
    _delay = 1.0
    _work_key = "greeting"
    _interaction_key = "pat"
    _last_result = "Not run yet"
    _last_run_at = ""

    _friend_trade_url = "https://pandapt.net/friend-trade.php"
    _ajax_url = "https://pandapt.net/ajax.php"

    def init_plugin(self, config: dict = None):
        self.stop_service()

        if config:
            self._enabled = bool(config.get("enabled"))
            self._onlyonce = bool(config.get("onlyonce"))
            self._notify = bool(config.get("notify", True))
            self._cookie = (config.get("cookie") or "").strip()
            self._cron = (config.get("cron") or "0 7 * * *").strip()
            self._delay = self.__float_value(config.get("delay"), 1.0)
            self._work_key = (config.get("work_key") or "greeting").strip()
            self._interaction_key = (config.get("interaction_key") or "pat").strip()
            self._last_result = config.get("last_result") or self._last_result
            self._last_run_at = config.get("last_run_at") or self._last_run_at

        if self._onlyonce:
            self._scheduler = BackgroundScheduler(timezone=settings.TZ)
            self._scheduler.add_job(
                func=self.run_daily,
                trigger="date",
                run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=3),
                name="PANDA Daily",
            )
            self._onlyonce = False
            self.__update_config()
            if self._scheduler.get_jobs():
                self._scheduler.print_jobs()
                self._scheduler.start()

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        return []

    def get_api(self) -> List[Dict[str, Any]]:
        return []

    def get_service(self) -> List[Dict[str, Any]]:
        if not self._enabled:
            return []
        if not self._cron:
            logger.warning("PANDA Daily cron is empty; service is not started")
            return []
        try:
            return [{
                "id": "PandaDaily",
                "name": "PANDA Daily",
                "trigger": CronTrigger.from_crontab(self._cron),
                "func": self.run_daily,
                "kwargs": {},
            }]
        except Exception as err:
            logger.error(f"PANDA Daily cron error: {err}")
            return []

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        return [
            {
                "component": "VForm",
                "content": [
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 3},
                                "content": [{
                                    "component": "VSwitch",
                                    "props": {"model": "enabled", "label": "Enable plugin"},
                                }],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 3},
                                "content": [{
                                    "component": "VSwitch",
                                    "props": {"model": "notify", "label": "Send notification"},
                                }],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 3},
                                "content": [{
                                    "component": "VSwitch",
                                    "props": {"model": "onlyonce", "label": "Run once now"},
                                }],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 3},
                                "content": [{
                                    "component": "VTextField",
                                    "props": {
                                        "model": "delay",
                                        "label": "Request delay seconds",
                                        "placeholder": "Default: 1",
                                    },
                                }],
                            },
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [{
                                    "component": "VCronField",
                                    "props": {
                                        "model": "cron",
                                        "label": "Cron schedule",
                                        "placeholder": "Default: 0 7 * * *",
                                    },
                                }],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 3},
                                "content": [{
                                    "component": "VTextField",
                                    "props": {
                                        "model": "work_key",
                                        "label": "Work key",
                                        "placeholder": "greeting",
                                    },
                                }],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 3},
                                "content": [{
                                    "component": "VTextField",
                                    "props": {
                                        "model": "interaction_key",
                                        "label": "Interaction key",
                                        "placeholder": "pat",
                                    },
                                }],
                            },
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [{
                                    "component": "VTextarea",
                                    "props": {
                                        "model": "cookie",
                                        "label": "PANDA Cookie",
                                        "rows": 4,
                                        "placeholder": "Paste the Cookie request header from a logged-in pandapt.net browser session.",
                                    },
                                }],
                            },
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [{
                                    "component": "VAlert",
                                    "props": {
                                        "type": "info",
                                        "variant": "tonal",
                                        "text": "Defaults: run at 07:00 daily, work_key=greeting, interaction_key=pat. Cookie is equivalent to a logged-in session.",
                                    },
                                }],
                            },
                        ],
                    },
                ],
            },
        ], {
            "enabled": False,
            "notify": True,
            "onlyonce": False,
            "cron": "0 7 * * *",
            "delay": 1,
            "work_key": "greeting",
            "interaction_key": "pat",
            "cookie": "",
            "last_result": "",
            "last_run_at": "",
        }

    def get_page(self) -> List[dict]:
        return [{
            "component": "VAlert",
            "props": {
                "type": "info",
                "variant": "tonal",
                "text": f"Last run: {self._last_run_at or 'none'}; result: {self._last_result or 'none'}",
            },
        }]

    def stop_service(self):
        try:
            if self._scheduler:
                self._scheduler.remove_all_jobs()
                if self._scheduler.running:
                    self._scheduler.shutdown()
        except Exception as err:
            logger.error(f"PANDA Daily stop service failed: {err}")
        finally:
            self._scheduler = None

    def run_daily(self):
        logger.info("PANDA Daily started")
        self._last_run_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        try:
            result = self.__run()
            self._last_result = result
            logger.info(f"PANDA Daily finished: {result}")
            if self._notify:
                self.__notify("PANDA Daily finished", result)
        except Exception as err:
            self._last_result = f"Failed: {err}"
            logger.error(f"PANDA Daily failed: {err}\n{traceback.format_exc()}")
            if self._notify:
                self.__notify("PANDA Daily failed", self._last_result)
        finally:
            self.__update_config()

    def __run(self) -> str:
        if not self._cookie:
            raise RuntimeError("Cookie is empty")

        page = self.__request_text(self._friend_trade_url)
        assets = self.__extract_assets(page)
        if not assets:
            raise RuntimeError("No friend-trade assets found. Cookie may be expired.")

        work_done = 0
        work_skip = 0
        interact_done = 0
        interact_skip = 0

        for asset in assets:
            name = asset.get("username")
            uid = asset.get("slave_uid")
            summary = asset.get("cultivation_summary") or {}
            if summary.get("can_work_today"):
                response = self.__post_action("friendTradeWork", {
                    "target_uid": uid,
                    "work_key": self._work_key,
                })
                self.__ensure_ok(response, f"{name} work")
                work_done += 1
                self.__sleep()
            else:
                work_skip += 1

        for asset in assets:
            name = asset.get("username")
            uid = asset.get("slave_uid")
            summary = asset.get("cultivation_summary") or {}
            if summary.get("can_interact_today"):
                response = self.__post_action("friendTradeInteract", {
                    "target_uid": uid,
                    "interaction_key": self._interaction_key,
                })
                self.__ensure_ok(response, f"{name} interaction")
                interact_done += 1
                self.__sleep()
            else:
                interact_skip += 1

        income_response = self.__post_action("friendTradeClaimIncome")
        self.__ensure_ok(income_response, "claim income")
        claimed_amount = (
            (income_response.get("data") or {}).get("claimed_amount")
            or (income_response.get("data") or {}).get("amount")
            or "0"
        )

        return (
            f"assets={len(assets)}, work_done={work_done}, work_skip={work_skip}, "
            f"interact_done={interact_done}, interact_skip={interact_skip}, "
            f"claimed=+{claimed_amount}"
        )

    def __request_text(self, url: str) -> str:
        request = Request(url, headers=self.__headers())
        with urlopen(request, timeout=30) as response:
            return response.read().decode("utf-8", errors="replace")

    def __post_action(self, action: str, params: dict[str, Any] = None) -> dict[str, Any]:
        params = params or {}
        body = {"action": action}
        for key, value in params.items():
            body[f"params[{key}]"] = str(value)

        data = urlencode(body).encode("utf-8")
        headers = self.__headers()
        headers.update({
            "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
        })
        request = Request(self._ajax_url, data=data, headers=headers, method="POST")
        with urlopen(request, timeout=30) as response:
            raw = response.read().decode("utf-8", errors="replace")
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"ret": -1, "msg": "Non-JSON response", "raw": raw[:500]}

    def __headers(self) -> dict[str, str]:
        return {
            "Cookie": self._cookie,
            "User-Agent": "Mozilla/5.0 MoviePilot PandaDaily",
            "Referer": self._friend_trade_url,
        }

    @staticmethod
    def __extract_assets(page_html: str) -> list[dict[str, Any]]:
        script_match = re.search(r"new Vue\(\{\s*el:\s*'#app'.*?\n\}\);", page_html, re.S)
        if not script_match:
            raise RuntimeError("Could not find friend-trade page data. You may not be logged in.")

        script = unescape(script_match.group(0))
        home_match = re.search(r"home:\s*(\{.*?\}),\s*assetPage:", script, re.S)
        if not home_match:
            raise RuntimeError("Could not parse friend-trade page data.")

        home = json.loads(home_match.group(1))
        return home.get("my_assets") or []

    @staticmethod
    def __ensure_ok(response: dict[str, Any], label: str):
        if response.get("ret") != 0:
            raise RuntimeError(f"{label} failed: {response.get('msg') or response}")

    def __sleep(self):
        if self._delay > 0:
            import time
            time.sleep(self._delay)

    def __notify(self, title: str, text: str):
        post_message = getattr(self, "post_message", None)
        if not callable(post_message):
            return
        try:
            if NotificationType:
                post_message(mtype=NotificationType.Plugin, title=title, text=text)
            else:
                post_message(title=title, text=text)
        except TypeError:
            try:
                post_message(title=title, text=text)
            except Exception as err:
                logger.warning(f"PANDA Daily notification failed: {err}")
        except Exception as err:
            logger.warning(f"PANDA Daily notification failed: {err}")

    def __update_config(self):
        self.update_config({
            "enabled": self._enabled,
            "notify": self._notify,
            "onlyonce": self._onlyonce,
            "cron": self._cron,
            "delay": self._delay,
            "work_key": self._work_key,
            "interaction_key": self._interaction_key,
            "cookie": self._cookie,
            "last_result": self._last_result,
            "last_run_at": self._last_run_at,
        })

    @staticmethod
    def __float_value(value: Any, default: float) -> float:
        try:
            return float(value)
        except Exception:
            return default
