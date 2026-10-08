"""Payload-free timings for nested extraction stages and provider sends."""
from contextvars import ContextVar
from functools import wraps
import logging
import re
import time
import uuid

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
if not logger.hasHandlers():
    logger.addHandler(logging.StreamHandler())
_trace = ContextVar("pdf2md_timing", default=None)
_stage = ContextVar("pdf2md_stage", default="unknown")


def provider_send():
    trace = _trace.get()
    if trace is not None:
        trace["sends"] += 1
        logger.info("pdf2md_provider_send trace=%s stage=%s send=%d",
                    trace["id"], _stage.get(), trace["sends"])


def stage_identity(task_id, page_no):
    trace = _trace.get()
    if trace is not None:
        task = task_id if isinstance(task_id, str) and re.fullmatch(r"task_[a-f0-9]+", task_id) else "unknown"
        page = page_no if type(page_no) is int else 0
        logger.info("pdf2md_page trace=%s task=%s page=%d", trace["id"], task, page)


def timed_stage(name):
    def decorate(fn):
        @wraps(fn)
        def run(*args, **kwargs):
            trace = _trace.get()
            token = None
            if trace is None:
                trace = {"id": uuid.uuid4().hex[:12], "sends": 0}
                token = _trace.set(trace)
            stage_token = _stage.set(name)
            started, sends = time.monotonic(), trace["sends"]
            status = "ok"
            logger.info("pdf2md_stage_start trace=%s stage=%s", trace["id"], name)
            try:
                return fn(*args, **kwargs)
            except BaseException:
                status = "error"
                raise
            finally:
                logger.info("pdf2md_stage_end trace=%s stage=%s status=%s elapsed_ms=%d sends=%d",
                            trace["id"], name, status, (time.monotonic()-started)*1000,
                            trace["sends"]-sends)
                _stage.reset(stage_token)
                if token is not None:
                    _trace.reset(token)
        return run
    return decorate
