import requests
import json
import os
import logging
from enum import Enum
from typing import Dict, List, Optional, Tuple, Union
from dataclasses import dataclass, asdict
from pypushdeer import PushDeer
from logging_config import init_logger


class CheckinStatus(Enum):
    """签到状态"""
    SUCCESS = 0
    REPEAT = 1
    FAILURE = -2


class ExchangePlan(Enum):
    """兑换计划"""
    PLAN100 = "plan100"
    PLAN200 = "plan200"
    PLAN500 = "plan500"


class APIEndpoint(Enum):
    """API端点"""
    CHECKIN = "/api/user/checkin"
    STATUS = "/api/user/status"
    POINTS = "/api/user/points"
    EXCHANGE = "/api/user/exchange"


class LogEmoji:
    """日志 Emoji"""
    SUCCESS = "✅"
    FAIL = "❌"
    REPEAT = "🔄"
    PENDING = "⏳"
    CHECKIN = "🎫"
    STATUS = "📊"
    POINTS = "💰"
    EXCHANGE = "🎁"
    START = "🚀"
    END = "🏁"
    COOKIE = "🍪"
    DOMAIN = "🌐"
    WARNING = "⚠️ "
    ERROR = "🔴"
    INFO = "ℹ️ "


def log_method(func):
    """日志装饰器"""
    def wrapper(self, *args, **kwargs):
        method_name = func.__name__
        emoji_map = {
            "checkin": LogEmoji.CHECKIN,
            "get_status": LogEmoji.STATUS,
            "get_points": LogEmoji.POINTS,
            "exchange": LogEmoji.EXCHANGE,
        }
        emoji = emoji_map.get(method_name, LogEmoji.INFO)
        try:
            result = func(self, *args, **kwargs)
            return result
        except Exception as e:
            logger.error(f"{LogEmoji.COOKIE}[{self.cookie_index}] {LogEmoji.DOMAIN}[{self.domain}] {emoji} {method_name} 执行失败: {e}")
            DEFAULT_ERRORS = {
                "checkin": {"status": "签到失败", "points": "0", "message": ""},
                "get_status": ("None 天", -2),
                "get_points": ("None 积分", 0),
                "exchange": "",
            }
            if method_name in DEFAULT_ERRORS:
                error_template = DEFAULT_ERRORS[method_name]
                if isinstance(error_template, dict):
                    error_result = error_template.copy()
                    error_result["message"] = f"执行失败: {e}"
                    return error_result
                return error_template
            raise
    return wrapper


class Config:
    """应用配置"""
    ENV_PUSH_KEY = "PUSHDEER_SENDKEY"
    ENV_PUSHPLUS_KEY = "PUSHPLUS_SENDKEY"
    ENV_COOKIES = "GLADOS_COOKIES"
    ENV_EXCHANGE_PLAN = "GLADOS_EXCHANGE_PLAN"
    ENV_VERBOSE = "GLADOS_VERBOSE"
    """默认兑换计划（none 表示不自动兑换）"""
    DEFAULT_EXCHANGE_PLAN = "none"
    """默认是否输出详细响应"""
    DEFAULT_VERBOSE = False
    """默认域名"""
    DOMAINS = ["glados.cloud"]
    """兑换计划列表"""
    EXCHANGE_PLANS = {
        ExchangePlan.PLAN100.value: 100,
        ExchangePlan.PLAN200.value: 200,
        ExchangePlan.PLAN500.value: 500,
    }

    def __init__(self):
        self.push_key: str = ""
        self.pushplus_key: str = ""
        self.cookies_list: List[str] = []
        self.exchange_plan: str = self.DEFAULT_EXCHANGE_PLAN
        self.verbose: bool = self.DEFAULT_VERBOSE
        self._load_config()

    def _load_config(self) -> None:
        """加载配置"""
        push_key_env: Optional[str] = os.environ.get(self.ENV_PUSH_KEY)
        pushplus_key_env: Optional[str] = os.environ.get(self.ENV_PUSHPLUS_KEY)
        raw_cookies_env: Optional[str] = os.environ.get(self.ENV_COOKIES)
        exchange_plan_env: Optional[str] = os.environ.get(self.ENV_EXCHANGE_PLAN)
        verbose_env: Optional[str] = os.environ.get(self.ENV_VERBOSE)

        if not push_key_env:
            logger.warning(f"{LogEmoji.WARNING} 环境变量 '{self.ENV_PUSH_KEY}' 未设置。")
            self.push_key = ""
        else:
            self.push_key = push_key_env

        if not pushplus_key_env:
            logger.warning(f"{LogEmoji.WARNING} 环境变量 '{self.ENV_PUSHPLUS_KEY}' 未设置，跳过PushPlus推送。")
            self.pushplus_key = ""
        else:
            self.pushplus_key = pushplus_key_env

        if not raw_cookies_env:
            logger.warning(f"{LogEmoji.WARNING} 环境变量 '{self.ENV_COOKIES}' 未设置。")
            self.cookies_list = []
        else:
            self.cookies_list = [cookie.strip() for cookie in raw_cookies_env.split("&") if cookie.strip()]
            if not self.cookies_list:
                raise ValueError(f"环境变量 '{self.ENV_COOKIES}' 已设置，但未包含任何有效的 Cookie。")

        if not exchange_plan_env:
            logger.warning(f"{LogEmoji.WARNING} 环境变量 '{self.ENV_EXCHANGE_PLAN}' 未设置，将使用默认设置（不自动兑换）。")
            self.exchange_plan = self.DEFAULT_EXCHANGE_PLAN
        else:
            if exchange_plan_env in self.EXCHANGE_PLANS:
                self.exchange_plan = exchange_plan_env
                logger.info(f"{LogEmoji.SUCCESS} 使用指定的兑换计划: {self.exchange_plan}")
            else:
                logger.warning(f"{LogEmoji.WARNING} 环境变量 '{self.ENV_EXCHANGE_PLAN}' 的值 '{exchange_plan_env}' 无效，将跳过自动兑换。")
                self.exchange_plan = self.DEFAULT_EXCHANGE_PLAN

        logger.info(f"{LogEmoji.INFO} 共加载了 {len(self.cookies_list)} 个 Cookie 用于签到。")
        logger.info(f"{LogEmoji.INFO} {self.ENV_PUSH_KEY}: {'已设置' if push_key_env else '未设置'}。")
        logger.info(f"{LogEmoji.INFO} {self.ENV_PUSHPLUS_KEY}: {'已设置' if pushplus_key_env else '未设置'}。")
        logger.info(f"{LogEmoji.INFO} {self.ENV_EXCHANGE_PLAN}: {self.exchange_plan}。")

        if verbose_env is not None:
            verbose_env_lower = verbose_env.lower()
            if verbose_env_lower in ["true", "1", "yes", "y"]:
                self.verbose = True
            elif verbose_env_lower in ["false", "0", "no", "n"]:
                self.verbose = False
            else:
                logger.warning(f"{LogEmoji.WARNING} 环境变量 '{self.ENV_VERBOSE}' 的值 '{verbose_env}' 无效，将使用默认值 {self.DEFAULT_VERBOSE}。")
        logger.info(f"{LogEmoji.INFO} {self.ENV_VERBOSE}: {self.verbose}。")


class API:
    """API 调用"""
    CHECKIN_URL = APIEndpoint.CHECKIN.value
    STATUS_URL = APIEndpoint.STATUS.value
    POINTS_URL = APIEndpoint.POINTS.value
    EXCHANGE_URL = APIEndpoint.EXCHANGE.value

    def __init__(self, domain: str, cookie_index: int = 0, verbose: bool = False):
        self.domain: str = domain
        self.cookie_index: int = cookie_index
        self.verbose: bool = verbose
        self.headers: Dict[str, str] = self._get_headers()
        self.session = requests.Session()
        self.session.headers.update(self.headers)

    def __del__(self):
        """关闭 session"""
        self.close()

    def close(self) -> None:
        """关闭 session"""
        if hasattr(self, "session"):
            try:
                self.session.close()
            except Exception as e:
                logger.error(f"{LogEmoji.COOKIE}[{self.cookie_index}] {LogEmoji.DOMAIN}[{self.domain}] {LogEmoji.ERROR} 关闭 session 时发生错误: {e}")

    def _get_headers(self) -> Dict[str, str]:
        """获取请求头"""
        return {
            "origin": f"https://{self.domain}",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/102.0.0.0 Safari/537.36",
        }

    def _log(self, level: str, emoji: str, message: str, force: bool = False) -> None:
        """统一日志输出"""
        log_msg = f"{LogEmoji.COOKIE}[{self.cookie_index}] {LogEmoji.DOMAIN}[{self.domain}] {emoji} {message}"
        if force or self.verbose:
            if level == "info":
                logger.info(log_msg)
            elif level == "warning":
                logger.warning(log_msg)
            elif level == "error":
                logger.error(log_msg)

    def _get_full_url(self, path: str) -> str:
        """拼接完整url"""
        return f"https://{self.domain}{path}"

    def _make_request(self, url: str, method: str, data: Optional[Dict] = None, cookies: str = "") -> Optional[requests.Response]:
        """发送HTTP请求"""
        req_headers = self.headers.copy()
        req_headers["cookie"] = cookies
        try:
            if method.upper() == "POST":
                response = self.session.post(url, headers=req_headers, data=data, timeout=(60, 120))
            elif method.upper() == "GET":
                response = self.session.get(url, headers=req_headers, timeout=(60, 120))
            else:
                self._log("error", LogEmoji.ERROR, f"不支持的 HTTP 方法: {method}", force=True)
                return None
            if not response.ok:
                self._log("warning", LogEmoji.WARNING, f"请求失败，状态码 {response.status_code}。响应内容: {response.text}", force=True)
                return None
            return response
        except requests.exceptions.RequestException as e:
            self._log("error", LogEmoji.ERROR, f"请求异常: {e}", force=True)
            return None

    def _get_checkin_data(self) -> Dict[str, str]:
        """签到请求体"""
        return {"token": self.domain}

    @log_method
    def checkin(self, cookies: str) -> Dict[str, Union[str, CheckinStatus]]:
        """执行签到"""
        url = self._get_full_url(self.CHECKIN_URL)
        checkin_data = self._get_checkin_data()
        response = self._make_request(url, "POST", checkin_data, cookies)
        result = {
            "status": "签到失败",
            "points": "0",
            "message": "",
            "code": CheckinStatus.FAILURE,
        }
        if response:
            data = response.json()
            code = data.get("code", -1)
            message = data.get("message", "无消息")
            points = str(data.get("points", 0))
            if code == CheckinStatus.SUCCESS.value:
                self._log("info", LogEmoji.SUCCESS, f"code : {code}, points : {points}, message : {message}")
                result["code"] = CheckinStatus.SUCCESS
                result["status"] = "签到成功"
                result["points"] = points
                result["message"] = message
            elif code == CheckinStatus.REPEAT.value:
                self._log("info", LogEmoji.REPEAT, f"code : {code}, message : {message}", force=True)
                result["code"] = CheckinStatus.REPEAT
                result["status"] = "重复签到"
                result["points"] = "0"
                result["message"] = message
            else:
                self._log("info", LogEmoji.FAIL, f"code : {code}, message : {message}", force=True)
                result["code"] = CheckinStatus.FAILURE
                result["status"] = "签到失败"
                result["points"] = "0"
                result["message"] = message
        else:
            self._log("warning", LogEmoji.WARNING, "签到请求无返回", force=True)
            result["code"] = CheckinStatus.FAILURE
            result["status"] = "签到失败"
            result["message"] = "网络请求失败"
        return result

    @log_method
    def get_status(self, cookies: str) -> Tuple[str, int]:
        """获取账号状态"""
        url = self._get_full_url(self.STATUS_URL)
        response = self._make_request(url, "GET", cookies=cookies)
        if response:
            data = response.json()
            left_days = data.get("data", {}).get("leftDays")
            if left_days is not None:
                left_days_int = int(float(left_days))
                self._log("info", LogEmoji.SUCCESS, f"leftDays : {left_days_int} 天")
                return f"{left_days_int} 天", 0
            else:
                self._log("info", LogEmoji.FAIL, f"leftDays 获取失败，原始返回: {data}", force=True)
                return "None 天", -1
        else:
            self._log("warning", LogEmoji.WARNING, "获取状态请求失败", force=True)
            return "None 天", -1

    @log_method
    def get_points(self, cookies: str) -> Tuple[str, int]:
        """获取积分"""
        url = self._get_full_url(self.POINTS_URL)
        response = self._make_request(url, "GET", cookies=cookies)
        if response:
            data = response.json()
            points = data.get("data")
            if points is not None:
                points_int = int(float(points))
                self._log("info", LogEmoji.SUCCESS, f"points : {points_int} 积分")
                return f"{points_int} 积分", points_int
            else:
                self._log("info", LogEmoji.FAIL, f"points 获取失败，原始返回: {data}", force=True)
                return "None 积分", 0
        else:
            self._log("warning", LogEmoji.WARNING, "获取积分请求失败", force=True)
            return "None 积分", 0

    @log_method
    def exchange(self, cookies: str, plan: str, required_points: int) -> str:
        """执行兑换"""
        url = self._get_full_url(self.EXCHANGE_URL)
        payload = {"planType": plan}
        response = self._make_request(url, "POST", payload, cookies)
        if response:
            data = response.json()
            code = data.get("code", -1)
            message = data.get("message", "未知")
            if code == 0:
                self._log("info", LogEmoji.SUCCESS, f"兑换成功:{plan}, message:{message}")
                return f"兑换成功:{plan}"
            else:
                self._log("info", LogEmoji.FAIL, f"兑换失败:{message}", force=True)
                return f"兑换失败:{message}"
        else:
            self._log("warning", LogEmoji.WARNING, "兑换请求失败", force=True)
            return "兑换失败"


@dataclass()
class CheckinResult:
    """签到结果"""
    cookie_index: int
    domain: str
    status: str = "签到失败"
    points: str = "0"
    days: str = "None"
    points_total: str = "None"
    exchange: str = "未兑换"
    code: CheckinStatus = CheckinStatus.FAILURE


class PushService:
    """推送服务"""
    def __init__(self, config: Config):
        self.config = config

    def send_pushdeer(self, title: str, content: str) -> bool:
        """发送PushDeer推送"""
        if not self.config.push_key:
            logger.info(f"{LogEmoji.WARNING} 未设置PushDeer密钥，跳过PushDeer推送。")
            return False
        try:
            pushdeer = PushDeer(pushkey=self.config.push_key)
            pushdeer.send_text(title, desp=content)
            logger.info(f"{LogEmoji.SUCCESS} PushDeer推送通知发送成功。")
            return True
        except Exception as e:
            logger.error(f"{LogEmoji.ERROR} PushDeer推送通知失败: {e}")
            return False

    def send_pushplus(self, title: str, content: str) -> bool:
        """发送PushPlus推送（markdown模板）"""
        if not self.config.pushplus_key:
            logger.info(f"{LogEmoji.WARNING} 未设置PushPlus密钥，跳过PushPlus推送。")
            return False
        url = "https://www.pushplus.plus/send"
        payload = {
            "token": self.config.pushplus_key,
            "title": title,
            "content": content,
            "template": "markdown"
        }
        try:
            resp = requests.post(url, json=payload, timeout=10)
            resp.raise_for_status()
            logger.info(f"{LogEmoji.SUCCESS} PushPlus推送通知发送成功。")
            return True
        except Exception as e:
            logger.error(f"{LogEmoji.ERROR} PushPlus推送通知失败: {str(e)}")
            return False

    def send(self, title: str, content: str) -> bool:
        """兼容原有PushDeer，保留旧入口"""
        return self.send_pushdeer(title, content)


class Checker:
    """签到主逻辑"""
    def __init__(self, config: Config):
        self.config = config
        self.results: List[CheckinResult] = []

    def _log(self, cookie_idx: int, domain: str, emoji: str, message: str, force: bool = False) -> None:
        """日志"""
        if self.config.verbose or force:
            logger.info(f"{LogEmoji.COOKIE}[{cookie_idx}] {LogEmoji.DOMAIN}[{domain}] {emoji} {message}")

    def checkin_all(self):
        """全部账号签到"""
        cookie_count = len(self.config.cookies_list)
        domain_count = len(self.config.DOMAINS)
        total_tasks = cookie_count * domain_count
        task_idx = 0
        logger.info(f"{LogEmoji.INFO} 共 {cookie_count} 个 Cookie, {domain_count} 个域名, 合计 {total_tasks} 任务")
        for cookie_idx, cookie in enumerate(self.config.cookies_list, 1):
            logger.info(f"{LogEmoji.START} ========== 开始处理 Cookie {cookie_idx} ==========")
            for domain in self.config.DOMAINS:
                task_idx += 1
                logger.info(f"{LogEmoji.INFO} ----- 任务 {task_idx}/{total_tasks}: Cookie{cookie_idx} @ {domain} -----")
                api = API(domain, cookie_index=cookie_idx, verbose=self.config.verbose)
                res = self._checkin_single(cookie, cookie_idx, domain, api)
                self.results.append(res)
                result_msg = f"结果: {res.status}"
                if res.code == CheckinStatus.SUCCESS:
                    if self.config.verbose:
                        result_msg = f"结果: {res.status}, 获得 {res.points} 积分, 剩余 {res.days}, 总 {res.points_total}, {res.exchange}"
                    self._log(cookie_idx, domain, LogEmoji.SUCCESS, result_msg, force=True)
                else:
                    self._log(cookie_idx, domain, LogEmoji.WARNING, result_msg, force=True)

    def _checkin_single(self, cookie: str, cookie_idx: int, domain: str, api: API) -> CheckinResult:
        """单个账号签到逻辑"""
        result = CheckinResult(cookie_index=cookie_idx, domain=domain)
        self._log(cookie_idx, domain, LogEmoji.STATUS, "查询账号剩余时长")
        days_str, _ = api.get_status(cookie)
        result.days = days_str

        self._log(cookie_idx, domain, LogEmoji.CHECKIN, "执行签到")
        checkin_ret = api.checkin(cookie)
        result.status = checkin_ret["status"]
        result.code = checkin_ret["code"]
        result.points = checkin_ret["points"]

        self._log(cookie_idx, domain, LogEmoji.POINTS, "查询总积分")
        total_points_str, _ = api.get_points(cookie)
        result.points_total = total_points_str

        # 自动兑换
        if self.config.exchange_plan in self.config.EXCHANGE_PLANS:
            required = self.config.EXCHANGE_PLANS[self.config.exchange_plan]
            self._log(cookie_idx, domain, LogEmoji.EXCHANGE, f"开始兑换 {self.config.exchange_plan} (需要 {required} 积分)")
            exchange_ret = api.exchange(cookie, self.config.exchange_plan, required)
            result.exchange = exchange_ret
        else:
            result.exchange = "未配置兑换计划，跳过自动兑换"
            self._log(cookie_idx, domain, LogEmoji.INFO, "未配置兑换计划，跳过自动兑换")
        return result

    def get_results(self) -> List[Dict[str, Union[str, CheckinStatus]]]:
        """转为字典列表"""
        return [asdict(r) for r in self.results]

    def format_results(self) -> Tuple[str, str, str, str, str]:
        """格式化结果：原有PushDeer纯文本 + PushPlus Markdown美化（修复换行）"""
        import time
        results = self.get_results()
        success_count = sum(1 for r in results if r["code"] == CheckinStatus.SUCCESS)
        repeat_count = sum(1 for r in results if r["code"] == CheckinStatus.REPEAT)
        fail_count = sum(1 for r in results if r["code"] == CheckinStatus.FAILURE)

        # ========== PushDeer 简单文本 ==========
        title_pushdeer = f"GLaDOS 签到, 成功{success_count}, 失败{fail_count}, 重复{repeat_count}"
        send_content_lines = []
        log_content_lines = []
        for i, res in enumerate(results, 1):
            line = f"#{i} P:{res['points']} 剩余:{res['days']} 总积分:{res['points_total']} | {res['status']} | {res['exchange']}"
            send_content_lines.append(line)
            if self.config.verbose:
                log_line = line
            else:
                log_line = f"#{i} {res['status']}"
            log_content_lines.append(log_line)
        content_pushdeer = "\n".join(send_content_lines)
        log_content = "\n".join(log_content_lines)

        # ========== PushPlus Markdown 美化消息，已修复换行 ==========
        sign_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        pushplus_body = f"""🎉Glados 自动签到通知
签到时间：{sign_time}

"""
        for res in results:
            try:
                today_point_int = int(float(res["points"]))
                today_point_str = f"{today_point_int}"
            except:
                today_point_str = res["points"]
            try:
                total_point_raw = res["points_total"].replace(" 积分", "")
                total_point_int = int(float(total_point_raw))
                total_point_str = f"{total_point_int}"
            except:
                total_point_str = res["points_total"]
            try:
                day_raw = res["days"].replace(" 天", "")
                day_int = int(float(day_raw))
                day_str = f"{day_int} 天"
            except:
                day_str = res["days"]

            email = f"Cookie{res['cookie_index']}"
            status_text = res["status"]
            exchange_text = res["exchange"]

            block = f"""📝{email} ✅
📄状态：{status_text}，获得 {today_point_str} 积分
🎁今日积分：{today_point_str}
📅剩余时长：{day_str}
💰总积分：{total_point_str} 积分
💎兑换：{exchange_text}

"""
            pushplus_body += block

        return title_pushdeer, content_pushdeer, log_content, "Glados 自动签到通知", pushplus_body


# 初始化日志
logger = init_logger()


def main():
    """主入口"""
    try:
        logger.info(f"{LogEmoji.START} ========== 启动 Glados 签到 ==========")
        config = Config()
        if not config.cookies_list:
            logger.error(f"{LogEmoji.ERROR} 未找到有效的 Cookie，退出程序。")
            title, content, log_content, pp_title, pp_content = "# 未找到 cookies!", "", "", "", ""
        else:
            checker = Checker(config)
            checker.checkin_all()
            logger.info(f"{LogEmoji.START} ========== 开始格式化推送内容 ==========")
            title, content, log_content, pp_title, pp_content = checker.format_results()
            logger.info(f"\n{LogEmoji.END}========== 签到总结 ==========\n{title}\n{log_content}")
    except Exception as e:
        logger.error(f"{LogEmoji.ERROR} 主程序执行异常: {e}")
        title, content, log_content, pp_title, pp_content = "# 脚本执行出错", str(e), str(e), "Glados签到异常", str(e)

    logger.info(f"{LogEmoji.START} ========== 开始发送推送 ==========")
    push_service = PushService(config if "config" in locals() else Config())
    push_service.send(title, content)
    push_service.send_pushplus(pp_title, pp_content)
    logger.info(f"{LogEmoji.END} ========== 签到任务结束 ==========")


if __name__ == "__main__":
    main()
