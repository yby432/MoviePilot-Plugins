import json
import re
import time
import traceback
from datetime import datetime, timedelta
from html import unescape
from itertools import combinations
from threading import Lock
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
    plugin_version = "1.6.0"
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
    _operation_lock = Lock()
    _work_key = "greeting"
    _interaction_key = "pat"
    _last_result = "尚未执行"
    _last_run_at = ""
    _last_daily_date = ""
    _office_next_run_at = ""

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
            self._last_daily_date = config.get("last_daily_date") or self._last_daily_date
            self._office_next_run_at = config.get("office_next_run_at") or ""

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

        if self._enabled and self._office_enabled:
            self.__schedule_office_cycle(
                self._office_next_run_at
                or datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=3)
            )

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        return []

    def get_api(self) -> List[Dict[str, Any]]:
        return []

    def get_service(self) -> List[Dict[str, Any]]:
        # MoviePilot 公共服务入口：执行周期格式对齐 AutoSignIn。
        jobs = []
        if self._enabled and self._cron:
            try:
                self._start_time = None
                self._end_time = None
                cron_text = str(self._cron).strip()
                if cron_text.count(" ") == 4:
                    jobs.append({
                        "id": "PandaDaily",
                        "name": "PANDA 每日任务",
                        "trigger": CronTrigger.from_crontab(cron_text),
                        "func": self.run_daily,
                        "kwargs": {},
                    })

                else:
                    crons = cron_text.split("/")
                    if len(crons) == 2:
                        interval_hours = crons[0]
                        times = crons[1].split("-")
                        if len(times) == 2:
                            self._start_time = int(times[0])
                            self._end_time = int(times[1])
                        if self._start_time is not None and self._end_time is not None:
                            jobs.append({
                                "id": "PandaDaily",
                                "name": "PANDA 每日任务",
                                "trigger": "interval",
                                "func": self.run_daily,
                                "kwargs": {"hours": float(str(interval_hours).strip())},
                            })
                        else:
                            logger.error("PANDA 每日任务启动失败，执行周期格式错误")
                    else:
                        jobs.append({
                            "id": "PandaDaily",
                            "name": "PANDA 每日任务",
                            "trigger": "interval",
                            "func": self.run_daily,
                            "kwargs": {"hours": float(cron_text)},
                        })
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
            for trigger in triggers:
                jobs.append({
                    "id": f"PandaDaily|{trigger.hour}:{trigger.minute}",
                    "name": "PANDA 每日任务",
                    "trigger": "cron",
                    "func": self.run_daily,
                    "kwargs": {
                        "hour": trigger.hour,
                        "minute": trigger.minute,
                    },
                })
        return jobs

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
                                            "每日工作、互动和收益与事务所独立运行。"
                                            "事务所会同时规划所有空闲栏位，优先填满栏位，"
                                            "再按属性匹配度和单位时间收益自动组队。"
                                            "事务所会在派遣时长结束2分钟后自动领取并续派，"
                                            "并从当前可用委托中自动选择最优方案。"
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
            "last_daily_date": "",
            "office_next_run_at": "",
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
        if not self._operation_lock.acquire(blocking=False):
            logger.info("PANDA 每日任务与其他任务冲突，2分钟后补跑")
            self.__schedule_daily_retry()
            return
        try:
            self.__run_daily_locked()
        finally:
            self._operation_lock.release()

    def __run_daily_locked(self):
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
        self._last_daily_date = datetime.now(tz=pytz.timezone(settings.TZ)).strftime("%Y-%m-%d")
        return (
            f"佣人 {len(assets)} 个；安排工作「{work_label}」完成 {work_done} 个，"
            f"不支持 {work_unavailable} 个，跳过 {work_skip} 个；"
            f"互动「{interaction_label}」完成 {interact_done} 个，跳过 {interact_skip} 个；"
            f"领取收益 +{claimed_amount} 魔力"
        )

    def run_office_cycle(self):
        if not self._operation_lock.acquire(blocking=False):
            logger.info("PANDA 事务所与每日任务冲突，2分钟后补跑")
            self.__schedule_office_cycle(
                datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(minutes=2)
            )
            return
        try:
            cookie = self.__resolve_cookie()
            if not cookie:
                raise RuntimeError("未配置 Cookie")
            settled = self.__settle_office(cookie)
            dispatched = self.__dispatch_office(cookie)
            if settled or dispatched:
                logger.info(
                    f"PANDA 事务所到期任务完成：领取 {settled} 项，派遣 {len(dispatched)} 项"
                    + (f"：{'、'.join(dispatched)}" if dispatched else "")
                )
        except Exception as err:
            logger.error(f"PANDA 事务所到期任务失败：{err}\n{traceback.format_exc()}")
            self.__schedule_office_cycle(
                datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(minutes=2)
            )
        finally:
            self._operation_lock.release()

    def __settle_office(self, cookie: str) -> int:
        board = self.__office_board(cookie)
        if not board.get("unlocked"):
            return 0

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
        return settled

    def __dispatch_office(self, cookie: str) -> List[str]:
        board = self.__office_board(cookie)
        if not board.get("unlocked"):
            return []
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

        if not self.__schedule_next_office_from_board(board):
            now = datetime.now(tz=pytz.timezone(settings.TZ))
            logger.warning("PANDA 事务所未返回有效结束时间，将在次日 00:02 再次检查")
            self.__schedule_office_cycle(
                (now + timedelta(days=1)).replace(
                    hour=0, minute=2, second=0, microsecond=0
                )
            )

        return dispatched

    def __schedule_next_office_from_board(self, board: dict[str, Any]) -> bool:
        timezone = pytz.timezone(settings.TZ)
        end_times = []
        for run in board.get("running") or []:
            ends_at = run.get("ends_at")
            if not ends_at:
                continue
            try:
                parsed = datetime.fromisoformat(str(ends_at))
                if parsed.tzinfo is None:
                    parsed = timezone.localize(parsed)
                end_times.append(parsed.astimezone(timezone))
            except (TypeError, ValueError):
                logger.warning(f"PANDA 事务所委托结束时间无效：{ends_at}")
        if not end_times:
            return False
        self.__schedule_office_cycle(min(end_times) + timedelta(minutes=2))
        return True

    def __schedule_office_cycle(self, run_at: Any):
        timezone = pytz.timezone(settings.TZ)
        if isinstance(run_at, str):
            try:
                run_at = datetime.fromisoformat(run_at)
            except ValueError:
                logger.warning(f"PANDA 事务所下次执行时间无效：{run_at}")
                self._office_next_run_at = ""
                self.__update_config()
                return
        if run_at.tzinfo is None:
            run_at = timezone.localize(run_at)
        else:
            run_at = run_at.astimezone(timezone)
        now = datetime.now(tz=timezone)
        if run_at <= now:
            run_at = now + timedelta(seconds=3)

        if not self._scheduler:
            self._scheduler = BackgroundScheduler(timezone=settings.TZ)
        self._scheduler.add_job(
            func=self.run_office_cycle,
            trigger="date",
            run_date=run_at,
            id="PandaDailyOffice",
            name="PANDA 事务所到期续派",
            replace_existing=True,
        )
        if not self._scheduler.running:
            self._scheduler.start()
        self._office_next_run_at = run_at.isoformat()
        self.__update_config()
        logger.info(f"PANDA 事务所下次续派时间：{run_at.strftime('%Y-%m-%d %H:%M:%S')}")

    def __schedule_daily_retry(self):
        run_at = datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(minutes=2)
        if not self._scheduler:
            self._scheduler = BackgroundScheduler(timezone=settings.TZ)
        self._scheduler.add_job(
            func=self.run_daily,
            trigger="date",
            run_date=run_at,
            id="PandaDailyRetry",
            name="PANDA 每日任务冲突补跑",
            replace_existing=True,
        )
        if not self._scheduler.running:
            self._scheduler.start()

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
    def __office_rating(match_score: float) -> Tuple[int, str, float]:
        """按事务所公布的评分门槛估算保底评级及奖励倍率。"""
        score = match_score * 100
        for threshold, rank, label, multiplier in (
            (175, 5, "SSS", 2.20),
            (140, 4, "SS", 1.75),
            (120, 3, "S", 1.45),
            (105, 2, "A", 1.20),
            (90, 1, "B", 1.00),
        ):
            if score >= threshold:
                return rank, label, multiplier
        return 0, "C", 0.75

    @staticmethod
    def __select_office_dispatch(
        board: dict[str, Any],
    ) -> Optional[Tuple[dict[str, Any], Tuple[dict[str, Any], ...]]]:
        offers = [
            offer for offer in board.get("offers") or []
            if not offer.get("is_started")
        ]
        members = [member for member in board.get("eligible_members") or [] if member.get("can_dispatch")]
        team_limit = int(board.get("team_size_limit") or 0)
        available_slots = max(
            0,
            int(board.get("parallel_limit") or 0) - len(board.get("running") or []),
        )
        if not offers or not members or team_limit < 1 or available_slots < 1:
            return None

        candidates = []
        for offer_index, offer in enumerate(offers):
            snapshot = offer.get("offer_snapshot_text") or {}
            team_size = min(
                max(1, int(snapshot.get("recommended_team_size") or 1)),
                team_limit,
                len(members),
            )
            targets = snapshot.get("focus_targets") or {}
            duration = max(1.0, float(snapshot.get("duration_hours") or 1))
            base_bonus = float(snapshot.get("base_bonus") or 0)
            base_exp = float(snapshot.get("base_exp") or 0)
            offer_candidates = []
            for team in combinations(members, team_size):
                match_score = 1.0
                coverage = 1.0
                if targets:
                    # 多人委托按每位成员的相关属性共同评分。属性超过推荐值仍会
                    # 提高评级，因此 match_score 不截断；coverage 仅用于日志展示。
                    ratios = [
                        float(
                            ((member.get("trait_summary") or {}).get("attributes") or {}).get(attribute)
                            or 0
                        ) / max(float(target), 1.0)
                        for member in team
                        for attribute, target in targets.items()
                    ]
                    match_score = sum(ratios) / len(ratios)
                    coverage = sum(min(ratio, 1.0) for ratio in ratios) / len(ratios)
                rating_rank, rating, reward_multiplier = PandaDaily.__office_rating(match_score)
                member_ids = frozenset(
                    member.get("relationship_id") or member.get("slave_uid") or id(member)
                    for member in team
                )
                offer_candidates.append({
                    "offer": offer,
                    "offer_key": offer.get("id") or offer_index,
                    "team": team,
                    "member_ids": member_ids,
                    "coverage": coverage,
                    "match_score": match_score,
                    "rating_rank": rating_rank,
                    "rating": rating,
                    "magic_rate": base_bonus * reward_multiplier / duration,
                    "exp_rate": base_exp * reward_multiplier / duration,
                    "base_bonus": base_bonus,
                })
            offer_candidates.sort(
                key=lambda item: (
                    item["magic_rate"], item["rating_rank"], item["match_score"],
                    item["exp_rate"], item["coverage"],
                ),
                reverse=True,
            )
            candidates.append(offer_candidates[:30])

        best_plan = []
        best_key = (-1, -1.0, -1, -1.0, -1.0, -1.0, -1.0)

        def plan_key(plan: list[dict[str, Any]]) -> tuple:
            return (
                len(plan),
                sum(item["magic_rate"] for item in plan),
                sum(item["rating_rank"] for item in plan),
                sum(item["match_score"] for item in plan),
                sum(item["exp_rate"] for item in plan),
                sum(item["coverage"] for item in plan),
                sum(item["base_bonus"] for item in plan),
            )

        def search(offer_index: int, plan: list[dict[str, Any]], used_members: set):
            nonlocal best_plan, best_key
            current_key = plan_key(plan)
            if current_key > best_key:
                best_key = current_key
                best_plan = list(plan)
            if len(plan) >= available_slots or offer_index >= len(candidates):
                return
            search(offer_index + 1, plan, used_members)
            for candidate in candidates[offer_index]:
                if candidate["member_ids"] & used_members:
                    continue
                plan.append(candidate)
                search(
                    offer_index + 1,
                    plan,
                    used_members | set(candidate["member_ids"]),
                )
                plan.pop()

        search(0, [], set())
        if not best_plan:
            return None
        selected = best_plan[0]
        logger.info(
            "PANDA 事务所智能分配：规划 %s 个栏位，首单预计评级 %s，"
            "全员属性匹配 %.1f%%，预计 %.1f 魔力/小时",
            len(best_plan),
            selected["rating"],
            selected["match_score"] * 100,
            selected["magic_rate"],
        )
        return selected["offer"], selected["team"]

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
            "last_daily_date": self._last_daily_date,
            "office_next_run_at": self._office_next_run_at,
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
