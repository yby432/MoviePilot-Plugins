from curl_cffi import requests
from app.plugins import PluginBase
from app.scheduler import Scheduler
from app.utils.notification import Notification

class Doki8CheckIn:
    def __init__(self, plugin: PluginBase):
        self.plugin = plugin
        self.cookie = self.plugin.get_config("doki8_cookie")
        self.cron = self.plugin.get_config("cron") or "0 8 * * *"
        # 首页：GET访问这里触发自动签到
        self.INDEX_URL = "http://www.doki8.net/"
        # 用户信息页，用来读取签到状态
        self.PROFILE_URL = "http://www.doki8.net/user"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "Referer": "http://www.doki8.net/",
            "Cookie": self.cookie
        }

    def run_checkin(self):
        if not self.cookie:
            msg = "Doki8签到：未配置Cookie，请前往插件设置填写"
            Notification().send(msg)
            return msg
        try:
            # 第一步：访问首页，触发登录即签到逻辑
            resp_index = requests.get(
                self.INDEX_URL,
                headers=self.headers,
                timeout=15,
                impersonate="chrome126"
            )
            if resp_index.status_code == 403:
                res_msg = "Doki8签到失败：触发Cloudflare人机验证"
                Notification().send(res_msg)
                return res_msg
            if "请登录" in resp_index.text:
                res_msg = "Doki8签到失败：Cookie已失效，请更新Cookie"
                Notification().send(res_msg)
                return res_msg

            # 第二步：访问个人页，读取签到结果
            resp_profile = requests.get(
                self.PROFILE_URL,
                headers=self.headers,
                timeout=15,
                impersonate="chrome126"
            )
            html = resp_profile.text

            # 根据页面文本判断状态，你可以浏览器打开/user页面，复制页面里实际的文字
            if "今日已签到" in html:
                res_msg = "Doki8：今日已签到"
            elif "签到成功" in html:
                res_msg = "Doki8签到成功"
            else:
                # 没有明确文字时，返回页面片段用于调试
                res_msg = f"Doki8已访问首页触发签到，页面片段：{html[:300]}"

        except Exception as e:
            res_msg = f"Doki8签到异常：{str(e)}"

        Notification().send(res_msg)
        return res_msg

    def register(self):
        Scheduler().add_cron_job(
            func=self.run_checkin,
            cron=self.cron,
            job_id="doki8_checkin",
            name="Doki8每日签到"
        )