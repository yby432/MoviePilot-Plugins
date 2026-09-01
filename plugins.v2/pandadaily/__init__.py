import json
import re
import time
import traceback
from datetime import datetime, timedelta
from html import unescape
from itertools import combinations
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.config import settings
from app.db.site_oper import SiteOper
from app.log import logger
from app.plugins import _PluginBase
from app.utils.timer import TimerUtils

try:
    from app.schemas.types import NotificationType
except Exception:
    NotificationType = None


class PandaDaily(_PluginBase):
    # 插件基础信息：这些字段会显示在 MoviePilot 插件市场和插件详情中。
    plugin_name = "PANDA 每日任务"
    plugin_desc = "自动完成 PANDA 好友买卖：工作、互动、领取每日收益。"
    plugin_icon = "signin.png"
    plugin_version = "1.1.0"
    plugin_author = "yby432"
    author_url = "https://github.com/jxxghp/MoviePilot-Plugins"
    plugin_config_prefix = "pandadaily_"
    plugin_order = 50
    auth_level = 1

    # 运行时状态与用户配置。
    _scheduler: Optional[BackgroundScheduler] = None
    _enabled = False
    _onlyonce = False
    _notify = True
    _cookie = ""
    _site_domain = "pandapt.net"
    _cron = ""
    _start_time: Optional[int] = None
    _end_time: Optional[int] = None
    _delay = 1.0
    _retry_count = 2
    _retry_interval = 60.0
    _office_enabled = True
    _work_key = "greeting"
    _interaction_key = "pat"
    _last_result = "尚未执行"
    _last_run_at = ""

    _friend_trade_url = "https://pandapt.net/friend-trade.php"
    _ajax_url = "https://pandapt.net/ajax.php"
    _work_options = [
        {"title": "打扫", "value": "clean"},
        {"title": "跑腿", "value": "errand"},
        {"title": "休息", "value": "rest"},
        {"title": "整理", "value": "tidy"},
        {"title": "迎客", "value": "greeting"},
        {"title": "陪聊", "value": "chat"},
        {"title": "洗头按摩", "value": "hair_massage"},
        {"title": "贴身照料", "value": "close_care"},
        {"title": "护主值守", "value": "guard"},
        {"title": "理财看账", "value": "accounting"},
        {"title": "私密差遣", "value": "private_task"},
        {"title": "外联应酬", "value": "social"},
        {"title": "大保健", "value": "special_care"},
        {"title": "暖侍加班", "value": "overtime"},
        {"title": "默契协作", "value": "tacit_cooperation"},
    ]
    _interaction_options = [
        {"title": "夸夸", "value": "praise"},
        {"title": "投喂", "value": "feed"},
        {"title": "摸头", "value": "pat"},
        {"title": "悄悄话", "value": "whisper"},
        {"title": "小奖励", "value": "reward"},
        {"title": "深入交流", "value": "deep_communication"},
    ]

    def init_plugin(self, config: dict = None):
        # 配置变更时先停止旧的一次性调度器，避免重复触发。
        self.stop_service()

        if config:
            self._enabled = bool(config.get("enabled"))
            self._onlyonce = bool(config.get("onlyonce"))
            self._notify = bool(config.get("notify", True))
            self._cookie = (config.get("cookie") or "").strip()
            self._site_domain = (config.get("site_domain") or "pandapt.net").strip()
            self._cron = (config.get("cron") or "").strip()
            self._delay = self.__float_value(config.get("delay"), 1.0)
            self._retry_count = max(0, self.__int_value(config.get("retry_count"), 2))
            self._retry_interval = max(0, self.__float_value(config.get("retry_interval"), 60.0))
            self._office_enabled = bool(config.get("office_enabled", True))
            self._work_key = (config.get("work_key") or "greeting").strip()
            self._interaction_key = (config.get("interaction_key") or "pat").strip()
            self._last_result = config.get("last_result") or self._last_result
            self._last_run_at = config.get("last_run_at") or self._last_run_at

        if self._onlyonce:
            # “立即运行一次”通过独立 BackgroundScheduler 延迟 3 秒执行，
            # 保存配置后插件宿主有时间完成刷新。
            self._scheduler = BackgroundScheduler(timezone=settings.TZ)
            self._scheduler.add_job(
                func=self.run_daily,
                trigger="date",
                run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=3),
                name="PANDA 每日任务",
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
        # MoviePilot 公共服务入口：执行周期格式对齐 AutoSignIn。
        if self._enabled and self._cron:
            try:
                self._start_time = None
                self._end_time = None
                cron_text = str(self._cron).strip()
                if cron_text.count(" ") == 4:
                    return [{
                        "id": "PandaDaily",
                        "name": "PANDA 每日任务",
                        "trigger": CronTrigger.from_crontab(cron_text),
                        "func": self.run_daily,
                        "kwargs": {},
                    }]

                crons = cron_text.split("/")
                if len(crons) == 2:
                    interval_hours = crons[0]
                    times = crons[1].split("-")
                    if len(times) == 2:
                        self._start_time = int(times[0])
                        self._end_time = int(times[1])
                    if self._start_time is not None and self._end_time is not None:
                        return [{
                            "id": "PandaDaily",
                            "name": "PANDA 每日任务",
                            "trigger": "interval",
                            "func": self.run_daily,
                            "kwargs": {"hours": float(str(interval_hours).strip())},
                        }]
                    logger.error("PANDA 每日任务启动失败，执行周期格式错误")
                else:
                    return [{
                        "id": "PandaDaily",
                        "name": "PANDA 每日任务",
                        "trigger": "interval",
                        "func": self.run_daily,
                        "kwargs": {"hours": float(cron_text)},
                    }]
            except Exception as err:
                logger.error(f"PANDA 每日任务定时任务配置错误：{err}")
        elif self._enabled:
            triggers = TimerUtils.random_scheduler(
                num_executions=1,
                begin_hour=9,
                end_hour=23,
                max_interval=6 * 60,
                min_interval=2 * 60,
            )
            ret_jobs = []
            for trigger in triggers:
                ret_jobs.append({
                    "id": f"PandaDaily|{trigger.hour}:{trigger.minute}",
                    "name": "PANDA 每日任务",
                    "trigger": "cron",
                    "func": self.run_daily,
                    "kwargs": {
                        "hour": trigger.hour,
                        "minute": trigger.minute,
                    },
                })
            return ret_jobs
        return []

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        # 使用 MoviePilot 的 Vuetify JSON 表单配置，无需单独前端页面。
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
                                    "component": "VTextField",
                                    "props": {
                                        "model": "retry_count",
                                        "label": "失败重试次数",
                                        "placeholder": "默认 2",
                                        "type": "number",
                                        "min": 0,
                                    },
                                }],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 3},
                                "content": [{
                                    "component": "VTextField",
                                    "props": {
                                        "model": "retry_interval",
                                        "label": "重试间隔秒数",
                                        "placeholder": "默认 60",
                                        "type": "number",
                                        "min": 0,
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
                                "props": {"cols": 12, "md": 3},
                                "content": [{
                                    "component": "VSwitch",
                                    "props": {"model": "enabled", "label": "启用插件"},
                                }],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 3},
                                "content": [{
                                    "component": "VSwitch",
                                    "props": {"model": "notify", "label": "发送通知"},
                                }],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 3},
                                "content": [{
                                    "component": "VSwitch",
                                    "props": {"model": "onlyonce", "label": "立即运行一次"},
                                }],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 3},
                                "content": [{
                                    "component": "VSwitch",
                                    "props": {"model": "office_enabled", "label": "自动派遣事务所"},
                                }],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 3},
                                "content": [{
                                    "component": "VTextField",
                                    "props": {
                                        "model": "delay",
                                        "label": "请求间隔秒数",
                                        "placeholder": "默认 1",
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
                                "props": {"cols": 12, "md": 4},
                                "content": [{
                                    "component": "VTextField",
                                    "props": {
                                        "model": "site_domain",
                                        "label": "MoviePilot 站点域名",
                                        "placeholder": "pandapt.net",
                                    },
                                }],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [{
                                    "component": "VTextField",
                                    "props": {
                                        "model": "cron",
                                        "label": "执行周期",
                                        "placeholder": "5位cron表达式，留空自动",
                                    },
                                }],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 2},
                                "content": [{
                                    "component": "VSelect",
                                    "props": {
                                        "model": "work_key",
                                        "label": "安排工作",
                                        "items": self._work_options,
                                        "item-title": "title",
                                        "item-value": "value",
                                    },
                                }],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 2},
                                "content": [{
                                    "component": "VSelect",
                                    "props": {
                                        "model": "interaction_key",
                                        "label": "今日互动",
                                        "items": self._interaction_options,
                                        "item-title": "title",
                                        "item-value": "value",
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
                                        "label": "备用 PANDA Cookie",
                                        "rows": 4,
                                        "placeholder": "通常留空；只有 MoviePilot 站点里没有 Cookie 时才需要填写",
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
                                        "text": (
                                            "执行周期支持：1、5位cron表达式；2、配置间隔（小时），"
                                            "如2.3/9-23（9-23点之间每隔2.3小时执行一次）；"
                                            "3、周期不填默认9-23点随机执行1次。"
                                            "任务失败后会按配置自动重试，默认重试2次、间隔60秒。"
                                            "开启自动派遣后会领取已完成委托，并按收益和属性匹配自动组队。"
                                        ),
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
            "cron": "",
            "delay": 1,
            "retry_count": 2,
            "retry_interval": 60,
            "office_enabled": True,
            "site_domain": "pandapt.net",
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
                "text": f"最近执行：{self._last_run_at or '暂无'}；结果：{self._last_result or '暂无'}",
            },
        }]

    def stop_service(self):
        # 停用插件或重新加载配置时清理一次性调度器。
        try:
            if self._scheduler:
                self._scheduler.remove_all_jobs()
                if self._scheduler.running:
                    self._scheduler.shutdown()
        except Exception as err:
            logger.error(f"PANDA 每日任务停止服务失败：{err}")
        finally:
            self._scheduler = None

    def run_daily(self):
        # 定时任务主入口：捕获所有异常并写入最近执行结果，避免后台服务崩溃。
        if self._start_time is not None and self._end_time is not None:
            current_hour = datetime.now().hour
            if current_hour < self._start_time or current_hour > self._end_time:
                logger.info(
                    f"PANDA 每日任务当前时间 {current_hour} 不在 {self._start_time}-{self._end_time} 范围内，暂不执行"
                )
                return

        logger.info("PANDA 每日任务开始执行")
        self._last_run_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        total_attempts = self._retry_count + 1
        for attempt in range(1, total_attempts + 1):
            try:
                result = self.__run()
                self._last_result = result
                logger.info(f"PANDA 每日任务执行完成：{result}")
                if self._notify:
                    self.__notify("PANDA 每日任务完成", result)
                break
            except Exception as err:
                if attempt < total_attempts:
                    logger.warning(
                        f"PANDA 每日任务第 {attempt} 次执行失败：{err}；"
                        f"{self._retry_interval:g} 秒后进行第 {attempt + 1} 次尝试"
                    )
                    if self._retry_interval > 0:
                        time.sleep(self._retry_interval)
                    continue

                self._last_result = f"执行失败（共尝试 {total_attempts} 次）：{err}"
                logger.error(f"PANDA 每日任务最终执行失败：{err}\n{traceback.format_exc()}")
                if self._notify:
                    self.__notify("PANDA 每日任务失败", self._last_result)
        self.__update_config()

    def __run(self) -> str:
        cookie = self.__resolve_cookie()
        if not cookie:
            raise RuntimeError("未配置 Cookie")

        # 先读取好友买卖首页，从页面内联 Vue 数据中解析佣人列表与今日状态。
        page = self.__request_text(self._friend_trade_url, cookie)
        assets = self.__extract_assets(page)
        if not assets:
            raise RuntimeError("未找到佣人资产，请检查 Cookie 是否有效")

        work_done = 0
        work_skip = 0
        work_unavailable = 0
        interact_done = 0
        interact_skip = 0
        work_label = self.__option_label(self._work_options, self._work_key)
        interaction_label = self.__option_label(self._interaction_options, self._interaction_key)

        for asset in assets:
            # can_work_today 为 True 时才提交工作，避免重复执行当天任务。
            name = asset.get("username")
            uid = asset.get("slave_uid")
            summary = asset.get("cultivation_summary") or {}
            if summary.get("can_work_today"):
                available_works = summary.get("available_works") or {}
                if available_works and self._work_key not in available_works:
                    work_unavailable += 1
                    logger.info(f"PANDA 每日任务跳过 {name}：暂不支持工作 {work_label}")
                    continue
                response = self.__post_action("friendTradeWork", {
                    "target_uid": uid,
                    "work_key": self._work_key,
                }, cookie)
                self.__ensure_ok(response, f"{name} 安排工作")
                work_done += 1
                self.__sleep()
            else:
                work_skip += 1

        for asset in assets:
            # can_interact_today 为 True 时才提交互动，默认 interaction_key=pat（摸头）。
            name = asset.get("username")
            uid = asset.get("slave_uid")
            summary = asset.get("cultivation_summary") or {}
            if summary.get("can_interact_today"):
                response = self.__post_action("friendTradeInteract", {
                    "target_uid": uid,
                    "interaction_key": self._interaction_key,
                }, cookie)
                self.__ensure_ok(response, f"{name} 今日互动")
                interact_done += 1
                self.__sleep()
            else:
                interact_skip += 1

        income_response = self.__post_action("friendTradeClaimIncome", cookie=cookie)
        self.__ensure_ok(income_response, "领取每日收益")
        claimed_amount = (
            (income_response.get("data") or {}).get("claimed_amount")
            or (income_response.get("data") or {}).get("amount")
            or "0"
        )
        office_result = self.__run_office(cookie) if self._office_enabled else "事务所未启用"

        return (
            f"佣人 {len(assets)} 个；安排工作「{work_label}」完成 {work_done} 个，"
            f"不支持 {work_unavailable} 个，跳过 {work_skip} 个；"
            f"互动「{interaction_label}」完成 {interact_done} 个，跳过 {interact_skip} 个；"
            f"领取收益 +{claimed_amount} 魔力；{office_result}"
        )

    def __run_office(self, cookie: str) -> str:
        board = self.__office_board(cookie)
        if not board.get("unlocked"):
            return f"事务所未解锁（Lv.{board.get('unlock_level') or '?'}）"

        settled = 0
        for run in board.get("running") or []:
            if not self.__office_run_ready(run, board.get("server_time")):
                continue
            response = self.__post_action(
                "friendTradeCommissionSettle", {"run_id": run.get("id")}, cookie
            )
            self.__ensure_ok(response, f"领取事务所委托 {run.get('id')}")
            settled += 1
            self.__sleep()

        if settled:
            board = self.__office_board(cookie)

        dispatched = []
        while len(board.get("running") or []) < int(board.get("parallel_limit") or 0):
            choice = self.__select_office_dispatch(board)
            if not choice:
                break
            offer, members = choice
            response = self.__post_action("friendTradeCommissionStart", {
                "offer_id": offer.get("id"),
                "relationship_ids": json.dumps(
                    [member.get("relationship_id") for member in members],
                    ensure_ascii=False,
                ),
            }, cookie)
            offer_name = (offer.get("offer_snapshot_text") or {}).get("name") or offer.get("name") or "未知委托"
            self.__ensure_ok(response, f"派遣事务所委托 {offer_name}")
            dispatched.append(
                f"{offer_name}（{', '.join(str(member.get('username')) for member in members)}）"
            )
            self.__sleep()
            board = self.__office_board(cookie)

        dispatch_text = "、".join(dispatched) if dispatched else "暂无可派遣栏位或队员"
        return f"事务所领取 {settled} 项，派遣 {len(dispatched)} 项：{dispatch_text}"

    def __office_board(self, cookie: str) -> dict[str, Any]:
        response = self.__post_action("friendTradeCommissionBoard", cookie=cookie)
        self.__ensure_ok(response, "读取事务所")
        data = response.get("data") or {}
        if not isinstance(data, dict):
            raise RuntimeError("事务所返回数据格式错误")
        return data

    @staticmethod
    def __office_run_ready(run: dict[str, Any], server_time: Any) -> bool:
        if run.get("status") in {"ready", "completed", "finished"}:
            return True
        ends_at = run.get("ends_at")
        if not ends_at or not server_time:
            return False
        try:
            return datetime.fromisoformat(str(ends_at)) <= datetime.fromisoformat(str(server_time))
        except (TypeError, ValueError):
            return False

    @staticmethod
    def __select_office_dispatch(
        board: dict[str, Any],
    ) -> Optional[Tuple[dict[str, Any], Tuple[dict[str, Any], ...]]]:
        offers = [offer for offer in board.get("offers") or [] if not offer.get("is_started")]
        members = [member for member in board.get("eligible_members") or [] if member.get("can_dispatch")]
        team_limit = int(board.get("team_size_limit") or 0)
        if not offers or not members or team_limit < 1:
            return None

        offers.sort(
            key=lambda offer: (
                float((offer.get("offer_snapshot_text") or {}).get("base_exp") or 0),
                float((offer.get("offer_snapshot_text") or {}).get("base_bonus") or 0),
            ),
            reverse=True,
        )
        offer = offers[0]
        snapshot = offer.get("offer_snapshot_text") or {}
        team_size = min(
            max(1, int(snapshot.get("recommended_team_size") or 1)),
            team_limit,
            len(members),
        )
        targets = snapshot.get("focus_targets") or {}

        def team_score(team: Tuple[dict[str, Any], ...]) -> float:
            score = 0.0
            for attribute, target in targets.items():
                best = max(
                    float(((member.get("trait_summary") or {}).get("attributes") or {}).get(attribute) or 0)
                    for member in team
                )
                score += min(best / max(float(target), 1.0), 1.0)
            return score

        return offer, max(combinations(members, team_size), key=team_score)

    def __resolve_cookie(self) -> str:
        site_cookie = self.__site_cookie()
        if site_cookie:
            return site_cookie
        return self._cookie

    def __site_cookie(self) -> str:
        domains = [self._site_domain, f"https://{self._site_domain}", f"http://{self._site_domain}"]
        for domain in domains:
            try:
                site = SiteOper().get_by_domain(domain)
                cookie = (getattr(site, "cookie", "") or "").strip() if site else ""
                if cookie:
                    logger.info(f"PANDA 每日任务已使用 MoviePilot 站点 Cookie：{domain}")
                    return cookie
            except Exception as err:
                logger.debug(f"PANDA 每日任务读取 MoviePilot 站点 Cookie 失败：{domain} - {err}")
        return ""

    def __request_text(self, url: str, cookie: str) -> str:
        request = Request(url, headers=self.__headers(cookie))
        with urlopen(request, timeout=30) as response:
            return response.read().decode("utf-8", errors="replace")

    def __post_action(self, action: str, params: dict[str, Any] = None, cookie: str = "") -> dict[str, Any]:
        # PANDA 好友买卖接口统一通过 ajax.php + action 调用。
        params = params or {}
        body = {"action": action}
        for key, value in params.items():
            body[f"params[{key}]"] = str(value)

        data = urlencode(body).encode("utf-8")
        headers = self.__headers(cookie)
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
            return {"ret": -1, "msg": "接口返回非 JSON", "raw": raw[:500]}

    def __headers(self, cookie: str) -> dict[str, str]:
        return {
            "Cookie": cookie,
            "User-Agent": "Mozilla/5.0 MoviePilot PandaDaily",
            "Referer": self._friend_trade_url,
        }

    @staticmethod
    def __extract_assets(page_html: str) -> list[dict[str, Any]]:
        # 新版页面把数据传给 normalizeFriendTradeHome({...})，旧版则直接写在 home: {...}。
        # 两种结构都通过括号配对提取 JSON，避免依赖换行和空格格式。
        script = unescape(page_html)
        bootstrap_key = re.search(
            r"\bfriendTradeBootstrapHome\s*=\s*normalizeFriendTradeHome\s*\(\s*\{",
            script,
        )
        home_key = bootstrap_key or re.search(r"\bhome\s*:\s*\{", script)
        if not home_key:
            if "login.php" in script or "logout.php" not in script:
                raise RuntimeError("未找到登录后的好友买卖数据，请检查 MoviePilot 站点 Cookie 是否有效")
            raise RuntimeError("无法找到好友买卖页面数据，可能页面结构已变化")

        object_start = script.find("{", home_key.start())
        object_end = PandaDaily.__find_matching_brace(script, object_start)
        if object_end < 0:
            raise RuntimeError("无法解析好友买卖页面数据")

        try:
            home = json.loads(script[object_start:object_end + 1])
        except json.JSONDecodeError as err:
            raise RuntimeError(f"好友买卖页面数据不是有效 JSON：{err}") from err
        return home.get("my_assets") or []

    @staticmethod
    def __find_matching_brace(text: str, start: int) -> int:
        depth = 0
        quote = ""
        escape = False
        for index in range(start, len(text)):
            char = text[index]
            if quote:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == quote:
                    quote = ""
                continue
            if char in ("'", '"'):
                quote = char
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return index
        return -1

    @staticmethod
    def __ensure_ok(response: dict[str, Any], label: str):
        if response.get("ret") != 0:
            raise RuntimeError(f"{label}失败：{response.get('msg') or response}")

    @staticmethod
    def __option_label(options: list[dict[str, str]], value: str) -> str:
        for option in options:
            if option.get("value") == value:
                return option.get("title") or value
        return value

    def __sleep(self):
        if self._delay > 0:
            time.sleep(self._delay)

    def __notify(self, title: str, text: str):
        # 不同 MoviePilot 版本的 post_message 签名可能略有不同，因此做兼容调用。
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
                logger.warning(f"PANDA 每日任务发送通知失败：{err}")
        except Exception as err:
            logger.warning(f"PANDA 每日任务发送通知失败：{err}")

    def __update_config(self):
        self.update_config({
            "enabled": self._enabled,
            "notify": self._notify,
            "onlyonce": self._onlyonce,
            "cron": self._cron,
            "delay": self._delay,
            "retry_count": self._retry_count,
            "retry_interval": self._retry_interval,
            "office_enabled": self._office_enabled,
            "site_domain": self._site_domain,
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

    @staticmethod
    def __int_value(value: Any, default: int) -> int:
        try:
            return int(value)
        except Exception:
            return default
