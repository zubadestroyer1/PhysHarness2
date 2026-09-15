import json
import logging
import sys

from physharness.logging import JsonFormatter


def test_correlated_failure_redacts_known_credentials_without_hiding_error():
    secret = "synthetic-private-provider-key"
    try:
        raise RuntimeError(f"provider refused Authorization: Bearer {secret}")
    except RuntimeError:
        record = logging.LogRecord(
            "physharness.worker",
            logging.ERROR,
            __file__,
            1,
            "Provider failed %s",
            (secret,),
            sys.exc_info(),
        )
    record.operation_id = "op-123"
    record.error_code = "PROVIDER_FAILED"
    encoded = JsonFormatter(redacted_values=[secret]).format(record)
    assert secret not in encoded
    output = json.loads(encoded)
    assert output["severity"] == "ERROR"
    assert output["operation_id"] == "op-123"
    assert output["error_code"] == "PROVIDER_FAILED"
    assert "RuntimeError" in output["traceback"]
    assert "[REDACTED]" in output["message"]
