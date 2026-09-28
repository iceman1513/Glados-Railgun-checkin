import os
import re
import time
import json
import requests
from dataclasses import dataclass
from typing import List, Tuple, Optional
from enum import Enum


class CheckinStatus(Enum):
    SUCCESS = "签到成功"
    REPEAT = "重复签到"
    FAILURE = "签到失败"


@dataclass
class Config:
    cookies: List[str]
    emails: List[str]
    pushdeer_key: Optional[str] = None
    pushplus_token: Optional[str] = None
    verbose: bool = False


@dataclass
class CheckinResult:
    cookie_index: int
    email: str
    code: CheckinStatus
    status: str
    points: str
    days: str
    points_total: str
    exchange: str


class GladosCheckin:
    def __init__(self, config: Config):
        self.config = config
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://glados.rocks/console/checkin",
        })

    def checkin(self, cookie: str, email: str, idx: int) -> CheckinResult:
        headers = {"Cookie": cookie}
        try:
            # 签到请求
            resp_checkin = self.session.post(
                "https://glados.rocks/api/user/checkin",
                headers=headers,
                json={"token": "glados.one"},
                timeout=20
            )
            checkin_data = resp_checkin.json()

            # 获取状态
            if checkin_data.get("code") == 0:
                status = CheckinStatus.SUCCESS
                msg = checkin_data.get("message", "")
            elif checkin_data.get("code") == 1:
                status = CheckinStatus.REPEAT
                msg = checkin_data.get("message", "")
            else:
                status = CheckinStatus.FAILURE
                msg = checkin_data.get("message", str(checkin_data))

            # 获取用户信息
            resp_user = self.session.get("https://glados.rocks/api/user/status", headers=headers, timeout=20)
            user_data = resp_user.json()

            points = user_data["data"]["points"]
            points_total = user_data["data"]["points"]
            left_days = int(float(user_data["data"]["leftDays"]))
            days = f"{left_days} 天"

            # 兑换操作
            exchange_resp = self.session.post(
                "https://glados.rocks/api/user/exchange",
                headers=headers,
                json={"plan": "plan500"},
                timeout=20
            )
            exchange_data = exchange_resp.json()
            exchange_msg = exchange_data.get("message", "")

            return CheckinResult(
                cookie_index=idx,
                email=email,
                code=status,
                status=msg,
                points=str(points),
                days=days,
                points_total=f"{points_total} 积分",
                exchange=exchange_msg
            )

        except Exception as e:
            return CheckinResult(
                cookie_index=idx,
                email=email,
                code=CheckinStatus.FAILURE,
                status=f"请求异常: {str(e)}",
                points="0",
                days="0 天",
                points_total="0 积分",
                exchange="兑换失败"
            )

    def get_results(self) -> List[CheckinResult]:
        res_list = []
        for index, (ck, mail) in enumerate(zip(self.config.cookies, self.config.emails)):
            print(f"===== 开始签到账号 {mail} =====")
            result = self.checkin(ck, mail, index + 1)
            res_list.append(result)
            print(f"结果: {result.status} | {result.exchange}")
            time.sleep(2)
        return res_list

    def format_results(self) -> Tuple[str, str, str, str, str]:
        """格式化结果：原有PushDeer纯文本 + PushPlus Markdown，一行一项，无多余空行"""
        import time
        import re
        def clean_float_str(text):
            """清理字符串里 .000000 这类多余小数"""
            return re.sub(r"(\d+)\.0+", r"\1", text)

        results = self.get_results()
        success_count = sum(1 for r in results if r["code"] == CheckinStatus.SUCCESS)
        repeat_count = sum(1 for r in results if r["code"] == CheckinStatus.REPEAT)
        fail_count = sum(1 for r in results if r["code"] == CheckinStatus.FAILURE)

        # ========== PushDeer 原有文本保持不变 ==========
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

        # ========== PushPlus：分行排版，和截图样式一致 ==========
        sign_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        pushplus_body = f"""📅签到时间：{sign_time}"""
        for res in results:
            # 数值清洗
            try:
                today_point_int = int(float(res.points))
                today_point_str = f"{today_point_int}"
            except:
                today_point_str = res.points

            try:
                total_point_raw = res.points_total.replace(" 积分", "")
                total_point_int = int(float(total_point_raw))
                total_point_str = f"{total_point_int}"
            except:
                total_point_str = res.points_total

            try:
                day_raw = res.days.replace(" 天", "")
                day_int = int(float(day_raw))
                day_str = f"{day_int} 天"
            except:
                day_str = res.days

            email = res.email
            status_text = res.status
            exchange_text = clean_float_str(res.exchange)

            # 账号内每一项单独换行；账号之间仅1个换行，无多余空白
            block = f"""
📝{email} ✅
📄状态：{status_text}，获得 {today_point_str} 积分
🎁今日积分：{today_point_str}
📅剩余时长：{day_str}
💰总积分：{total_point_str} 积分
💎兑换：{exchange_text}"""
            pushplus_body += block

        return title_pushdeer, content_pushdeer, log_content, "Glados 自动签到通知", pushplus_body

    def push_pushdeer(self, title: str, content: str):
        if not self.config.pushdeer_key:
            return
        try:
            url = f"https://api.pushdeer.com/message/push?pushkey={self.config.pushdeer_key}&text={title}&desp={content}"
            requests.get(url, timeout=15)
            print("PushDeer推送成功")
        except Exception as e:
            print(f"PushDeer推送失败：{e}")

    def push_pushplus(self, title: str, content: str):
        if not self.config.pushplus_token:
            return
        try:
            payload = {
                "token": self.config.pushplus_token,
                "title": title,
                "content": content,
                "template": "markdown"
            }
            requests.post("https://www.pushplus.plus/send", json=payload, timeout=15)
            print("PushPlus推送成功")
        except Exception as e:
            print(f"PushPlus推送失败：{e}")

    def run(self):
        title_pd, content_pd, log_content, title_pp, content_pp = self.format_results()
        self.push_pushdeer(title_pd, content_pd)
        self.push_pushplus(title_pp, content_pp)
        print("\n===== 签到全部完成 =====")
        print(log_content)


def main():
    # ============ 从环境变量读取配置 ============
    cookie_env = os.getenv("GLADOS_COOKIES", "")
    email_env = os.getenv("GLADOS_EMAILS", "")
    pushdeer_key = os.getenv("PUSHDEER_KEY", "")
    pushplus_token = os.getenv("PUSHPLUS_TOKEN", "")

    cookies = [ck.strip() for ck in cookie_env.split("|") if ck.strip()]
    emails = [mail.strip() for mail in email_env.split("|") if mail.strip()]

    if len(cookies) != len(emails):
        print("错误：Cookie数量和邮箱数量必须一一对应，用 | 分隔")
        return

    cfg = Config(
        cookies=cookies,
        emails=emails,
        pushdeer_key=pushdeer_key if pushdeer_key else None,
        pushplus_token=pushplus_token if pushplus_token else None,
        verbose=False
    )
    task = GladosCheckin(cfg)
    task.run()


if __name__ == "__main__":
    main()
