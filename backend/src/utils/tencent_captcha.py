"""腾讯云 Captcha 票据校验。

前端只提交 CaptchaAppId 对应的 ticket/randstr，AppSecretKey 和云 API 密钥
始终留在后端环境变量中。未开启强制校验时，保留兼容性，方便本地开发。
"""

import asyncio
import json
import logging
import os

logger = logging.getLogger(__name__)


def _response_value(response, name: str):
    """兼容腾讯 SDK 不同版本的直接字段和 Response 嵌套字段。"""
    value = getattr(response, name, None)
    if value is not None:
        return value
    nested = getattr(response, "Response", None)
    return getattr(nested, name, None) if nested is not None else None


def captcha_required() -> bool:
    return os.getenv("TENCENT_CAPTCHA_REQUIRED", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _configured() -> bool:
    return all(
        os.getenv(name, "").strip()
        for name in (
            "TENCENT_CAPTCHA_APP_ID",
            "TENCENT_CAPTCHA_APP_SECRET_KEY",
            "TENCENTCLOUD_SECRET_ID",
            "TENCENTCLOUD_SECRET_KEY",
        )
    )


def _verify_ticket_sync(ticket: str, randstr: str, user_ip: str) -> bool:
    if not _configured():
        logger.error("腾讯云验证码已强制开启，但后端密钥配置不完整")
        return False

    try:
        from tencentcloud.common import credential
        from tencentcloud.common.profile.client_profile import ClientProfile
        from tencentcloud.common.profile.http_profile import HttpProfile
        from tencentcloud.captcha.v20190722 import captcha_client, models

        http_profile = HttpProfile()
        http_profile.endpoint = "captcha.tencentcloudapi.com"
        http_profile.reqTimeout = 5

        client_profile = ClientProfile()
        client_profile.httpProfile = http_profile
        client = captcha_client.CaptchaClient(
            credential.Credential(
                os.environ["TENCENTCLOUD_SECRET_ID"].strip(),
                os.environ["TENCENTCLOUD_SECRET_KEY"].strip(),
            ),
            "",
            client_profile,
        )

        request = models.DescribeCaptchaResultRequest()
        request.from_json_string(
            json.dumps(
                {
                    "CaptchaType": 9,
                    "CaptchaAppId": int(os.environ["TENCENT_CAPTCHA_APP_ID"]),
                    "AppSecretKey": os.environ["TENCENT_CAPTCHA_APP_SECRET_KEY"].strip(),
                    "Ticket": ticket,
                    "Randstr": randstr,
                    "UserIp": user_ip or "127.0.0.1",
                    "NeedGetCaptchaTime": 0,
                }
            )
        )
        response = client.DescribeCaptchaResult(request)
        code = _response_value(response, "CaptchaCode")
        message = _response_value(response, "CaptchaMsg")
        request_id = _response_value(response, "RequestId") or _response_value(
            response, "RequestID"
        )
        # 腾讯云 DescribeCaptchaResult（2019-07-22）：CaptchaCode=1 表示验证通过。
        # 参考 https://cloud.tencent.com/document/product/1110/36926
        if str(code) == "1":
            logger.info("腾讯云验证码校验通过 request_id=%s", request_id)
            return True

        logger.warning(
            "腾讯云验证码票据未通过 code=%s message=%s request_id=%s",
            code,
            message,
            request_id,
        )
        return False
    except Exception:
        logger.exception("腾讯云验证码票据校验异常")
        return False


async def verify_ticket(ticket: str | None, randstr: str | None, user_ip: str) -> bool:
    """校验一次性票据；未强制开启时返回 True，避免影响未配置的本地环境。"""
    if not captcha_required():
        return True
    if not ticket or not randstr:
        return False
    return await asyncio.to_thread(_verify_ticket_sync, ticket, randstr, user_ip)
