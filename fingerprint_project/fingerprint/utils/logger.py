"""
Structured Logging Utility
──────────────────────────
JSON-style logging for biometric operations.
No fingerprint images are ever logged.
"""

import json
import logging
from datetime import datetime


class BiometricLogger:
    """Structured logger for biometric operations."""

    def __init__(self, name='fingerprint'):
        self.logger = logging.getLogger(name)

    def log_operation(self, operation_type, **kwargs):
        """
        Log a biometric operation with structured fields.

        Args:
            operation_type: e.g. 'upload', 'match', 'enroll', 'sensor_capture'
            **kwargs: Additional fields (user_id, match_score, result, etc.)
        """
        log_data = {
            'timestamp': datetime.utcnow().isoformat(),
            'operation': operation_type,
        }
        log_data.update(kwargs)

        # Never log image data
        for key in ['image', 'template_bytes', 'encrypted_template']:
            log_data.pop(key, None)

        self.logger.info(json.dumps(log_data))

    def log_upload(self, student_id, quality_score, minutiae_count, finger_type):
        self.log_operation(
            'fingerprint_upload',
            student_id=student_id,
            quality_score=quality_score,
            minutiae_count=minutiae_count,
            finger_type=finger_type,
            result='success',
        )

    def log_match(self, student_id, match_score, result, method):
        self.log_operation(
            'fingerprint_match',
            student_id=student_id,
            match_score=match_score,
            authentication_result=result,
            method=method,
        )

    def log_sensor_capture(self, student_id, minutiae_count, finger_type):
        self.log_operation(
            'sensor_capture',
            student_id=student_id,
            minutiae_count=minutiae_count,
            finger_type=finger_type,
            result='success',
        )

    def log_error(self, operation_type, error_message, **kwargs):
        self.log_operation(
            operation_type,
            result='error',
            error=error_message,
            **kwargs,
        )


# Global logger instance
biometric_logger = BiometricLogger()
