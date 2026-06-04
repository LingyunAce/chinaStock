#!/usr/bin/env python3
"""通知推送模块 - 邮件 / Server酱 / 企业微信 webhook 多通道推送。

支持渠道：
    1. 邮件（SMTP）：支持 QQ邮箱/163邮箱/Gmail
    2. Server酱（微信推送）：需 ScanCode 关注测试号，获取 SCT 密钥
    3. 企业微信 webhook：需在企业微信群创建机器人

配置方式（环境变量）：
    邮件：
        SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, MAIL_TO
    Server酱：
        SERVERCHAN_SCT  （在 https://sct.ftqq.com/ 申请）
    企业微信：
        WECOM_WEBHOOK    （企业微信群机器人 webhook URL）

使用示例：
    from scripts.notifier import Notifier
    n = Notifier()
    n.send_email(subject="A股复盘", html_body="<h1>...</h1>")
    n.send_serverchan("A股复盘", "今日沪指-0.64%...")
    n.send_wecom("## A股复盘\\n- 沪指-0.64%")
    n.send_all("A股复盘", html_body, markdown_text)  # 三通道同时发送
"""
from __future__ import annotations

import json
import os
import smtplib
import sys
import urllib.error
import urllib.parse
import urllib.request
import warnings
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from typing import Any

warnings.filterwarnings("ignore")


class Notifier:
    """多通道通知推送器。

    通过环境变量读取配置，缺失则跳过该通道。
    """

    def __init__(
        self,
        smtp_host: str | None = None,
        smtp_port: int | None = None,
        smtp_user: str | None = None,
        smtp_pass: str | None = None,
        mail_to: str | list[str] | None = None,
        serverchan_sct: str | None = None,
        wecom_webhook: str | None = None,
    ):
        self.smtp_host = smtp_host or os.environ.get("SMTP_HOST")
        self.smtp_port = int(smtp_port or os.environ.get("SMTP_PORT") or 465)
        self.smtp_user = smtp_user or os.environ.get("SMTP_USER")
        self.smtp_pass = smtp_pass or os.environ.get("SMTP_PASS")
        self.mail_to = mail_to or os.environ.get("MAIL_TO", "")
        if isinstance(self.mail_to, str) and self.mail_to:
            self.mail_to = [addr.strip() for addr in self.mail_to.split(",") if addr.strip()]

        self.serverchan_sct = serverchan_sct or os.environ.get("SERVERCHAN_SCT")
        self.wecom_webhook = wecom_webhook or os.environ.get("WECOM_WEBHOOK")

    def _enabled_channels(self) -> list[str]:
        """返回已配置的通道列表。"""
        channels = []
        if self.smtp_host and self.smtp_user and self.mail_to:
            channels.append("email")
        if self.serverchan_sct:
            channels.append("serverchan")
        if self.wecom_webhook:
            channels.append("wecom")
        return channels

    # ============ 邮件 ============
    def send_email(
        self,
        subject: str,
        html_body: str,
        from_name: str = "A股复盘机器人",
    ) -> bool:
        """发送邮件。

        Args:
            subject: 邮件主题
            html_body: HTML 内容
            from_name: 发件人显示名

        Returns:
            True 成功 / False 失败
        """
        if not self._enabled_channels() or "email" not in self._enabled_channels():
            print("  [email] 未配置 SMTP_HOST/SMTP_USER/MAIL_TO 环境变量，跳过")
            return False

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = formataddr([from_name, self.smtp_user])
        msg["To"] = ", ".join(self.mail_to)
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        try:
            if self.smtp_port == 465:
                # SSL
                with smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, timeout=15) as server:
                    server.login(self.smtp_user, self.smtp_pass)
                    server.sendmail(self.smtp_user, self.mail_to, msg.as_string())
            else:
                # STARTTLS
                with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=15) as server:
                    server.starttls()
                    server.login(self.smtp_user, self.smtp_pass)
                    server.sendmail(self.smtp_user, self.mail_to, msg.as_string())
            print(f"  [email] ✅ 发送成功: {len(self.mail_to)} 个收件人")
            return True
        except (smtplib.SMTPException, OSError) as e:
            print(f"  [email] ❌ 发送失败: {type(e).__name__}: {str(e)[:100]}")
            return False

    # ============ Server酱（微信推送） ============
    def send_serverchan(
        self,
        title: str,
        content: str,
        short: str | None = None,
    ) -> bool:
        """通过 Server酱 推送到微信。

        Args:
            title: 消息标题
            content: 消息内容（支持 Markdown）
            short: 简短描述（可选）
        """
        if "serverchan" not in self._enabled_channels():
            print("  [serverchan] 未配置 SERVERCHAN_SCT 环境变量，跳过")
            return False

        url = f"https://sctapi.ftqq.com/{self.serverchan_sct}.send"
        data = {
            "title": title,
            "desp": content,
        }
        if short:
            data["short"] = short

        encoded = urllib.parse.urlencode(data).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=encoded,
            headers={"User-Agent": "Mozilla/5.0"},
        )

        import socket
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        socket.setdefaulttimeout(10)
        try:
            with opener.open(req, timeout=10) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                if result.get("code") == 0:
                    print(f"  [serverchan] ✅ 微信推送成功")
                    return True
                else:
                    print(f"  [serverchan] ❌ 推送失败: {result.get('message', '?')}")
                    return False
        except (urllib.error.URLError, Exception) as e:
            print(f"  [serverchan] ❌ 网络错误: {type(e).__name__}: {str(e)[:100]}")
            return False

    # ============ 企业微信 webhook ============
    def send_wecom(self, content: str, mentioned_list: list[str] | None = None) -> bool:
        """通过企业微信 webhook 推送（支持 Markdown）。

        Args:
            content: Markdown 内容
            mentioned_list: @ 用户的 userid 列表
        """
        if "wecom" not in self._enabled_channels():
            print("  [wecom] 未配置 WECOM_WEBHOOK 环境变量，跳过")
            return False

        data = {
            "msgtype": "markdown",
            "markdown": {
                "content": content,
            },
        }
        if mentioned_list:
            data["markdown"]["mentioned_list"] = mentioned_list

        encoded = json.dumps(data).encode("utf-8")
        req = urllib.request.Request(
            self.wecom_webhook,
            data=encoded,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0",
            },
        )

        import socket
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        socket.setdefaulttimeout(10)
        try:
            with opener.open(req, timeout=10) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                if result.get("errcode") == 0:
                    print(f"  [wecom] ✅ 企业微信推送成功")
                    return True
                else:
                    print(f"  [wecom] ❌ 推送失败: {result.get('errmsg', '?')}")
                    return False
        except (urllib.error.URLError, Exception) as e:
            print(f"  [wecom] ❌ 网络错误: {type(e).__name__}: {str(e)[:100]}")
            return False

    # ============ 三通道同时推送 ============
    def send_all(
        self,
        subject: str,
        html_body: str,
        markdown_summary: str,
        from_name: str = "A股复盘机器人",
    ) -> dict[str, bool]:
        """三通道同时推送。

        Args:
            subject: 邮件主题 / Server酱 标题
            html_body: 邮件 HTML 内容
            markdown_summary: Server酱/企业微信使用的 Markdown 摘要

        Returns:
            {"email": bool, "serverchan": bool, "wecom": bool}
        """
        results = {}
        print(f"📤 开始推送（已配置通道: {self._enabled_channels()}）")
        results["email"] = self.send_email(subject, html_body, from_name)
        results["serverchan"] = self.send_serverchan(subject, markdown_summary)
        results["wecom"] = self.send_wecom(markdown_summary)
        return results


# ============ CLI 测试 ============
def _cli():
    """命令行测试接口。

    用法:
        python notifier.py test          # 测试当前配置
        python notifier.py channels      # 查看已配置通道
    """
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    n = Notifier()
    channels = n._enabled_channels()

    if len(sys.argv) < 2 or sys.argv[1] == "channels":
        print("🔍 已配置的通知通道：")
        if not channels:
            print("  ⚠️  无 - 请设置以下环境变量之一：")
            print()
            print("  邮件：")
            print("    export SMTP_HOST=smtp.qq.com")
            print("    export SMTP_PORT=465")
            print("    export SMTP_USER=xxx@qq.com")
            print("    export SMTP_PASS=授权码")
            print("    export MAIL_TO=alice@example.com,bob@example.com")
            print()
            print("  Server酱（微信推送）：")
            print("    export SERVERCHAN_SCT=SCT_xxxxx  # 在 https://sct.ftqq.com/ 申请")
            print()
            print("  企业微信 webhook：")
            print("    export WECOM_WEBHOOK='https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx'")
        else:
            for c in channels:
                print(f"  ✅ {c}")
        return

    if sys.argv[1] == "test":
        if not channels:
            print("❌ 没有配置任何通道，请先设置环境变量")
            return
        html_body = "<h1>测试推送</h1><p>这是一封来自 chinaStock 的测试邮件。</p>"
        md_summary = "## 测试推送\n\n- 来自 chinaStock 的测试消息"
        n.send_all("测试推送", html_body, md_summary, from_name="chinaStock 测试")


if __name__ == "__main__":
    _cli()
