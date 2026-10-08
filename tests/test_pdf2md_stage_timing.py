import importlib
import logging
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import pytest
from tests.test_pdf2md_enhanced_single_page_tools import single_page_tools

timing = importlib.import_module(single_page_tools.__package__ + '.stage_timing')


def test_nested_stage_reports_failure_counts_without_payload(caplog):
    @timing.timed_stage('inner')
    def inner(secret):
        timing.stage_identity(secret, 13)
        timing.provider_send()
        raise ValueError(secret)
    @timing.timed_stage('outer')
    def outer(secret):
        inner(secret)
    with caplog.at_level(logging.INFO), pytest.raises(ValueError):
        outer('private-source-and-token')
    assert 'private-source-and-token' not in caplog.text
    assert 'stage=inner status=error' in caplog.text
    assert 'stage=outer status=error' in caplog.text
    assert 'sends=1' in caplog.text
    assert timing._trace.get() is None
    assert timing._stage.get() == 'unknown'


def test_concurrent_pages_do_not_share_counters():
    barrier = Barrier(2)
    @timing.timed_stage('page')
    def page(count):
        barrier.wait()
        for _ in range(count):
            timing.provider_send()
        return dict(timing._trace.get())
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(page, [1, 3]))
    assert [r['sends'] for r in results] == [1, 3]
    assert results[0]['id'] != results[1]['id']
