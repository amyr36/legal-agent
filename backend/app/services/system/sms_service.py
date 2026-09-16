from __future__ import annotations

import logging

from melipayamak import Api

from app.core.config import settings


logger = logging.getLogger(__name__)


class SMSService:
    def __init__(self) -> None:
        api = Api(
            settings.MELIPAYAMAK_USERNAME,
            settings.MELIPAYAMAK_PASSWORD.get_secret_value(),
        )

        self._sms = api.sms()

    def send_otp(
        self,
        phone_number: str,
        code: str,
    ) -> bool:
        """Send an OTP SMS.

        Returns:
            True if the SMS provider accepts the request.
            False if sending fails.
        """

        try:
            result = self._sms.send_otp(
                phone_number,
                settings.MELIPAYAMAK_SENDER,
                code,
            )

            if self._is_successful_response(result):
                return True

            logger.error(
                "Melipayamak returned an unsuccessful response: %s",
                result,
            )

            return False

        except Exception:
            logger.exception(
                "Failed to send OTP to %s",
                phone_number,
            )
            return False

    @staticmethod
    def _is_successful_response(result: object) -> bool:
        """Check whether Melipayamak returned a successful response."""

        return (
            isinstance(result, (int, str))
            and str(result).isdigit()
        )


sms_service = SMSService()