from threading import Barrier, Event, Lock

import pytest

from casepilot_agent.planning import analyze_batches


def test_concurrency_bound_order_and_checkpoint_before_progress():
    barrier, release = Barrier(3, timeout=3), Event()
    lock = Lock()
    current = peak = 0
    saved, progress = {}, []

    def complete(index, batch):
        nonlocal current, peak
        with lock:
            current += 1
            peak = max(peak, current)
        if index < 3:
            barrier.wait()
        if index == 0:
            assert release.wait(3)
        with lock:
            current -= 1
        return batch * 2

    def publish(done, total, active):
        assert done == len(saved)
        progress.append(done)
        if 1 in saved:
            release.set()

    result = analyze_batches(
        list(range(8)), complete, load=lambda i, b: None,
        save=lambda i, b, result: saved.__setitem__(i, result),
        on_progress=publish, check_cancelled=lambda: None,
    )
    assert result == [i * 2 for i in range(8)]
    assert peak == 3
    assert progress == sorted(progress)


def test_failed_batch_retry_reuses_completed_and_drains_inflight_successes():
    barrier = Barrier(3, timeout=3)
    saved, called = {}, []

    def complete(index, batch):
        called.append(index)
        barrier.wait()
        if index == 1:
            raise ValueError('failed')
        return batch

    args = dict(load=lambda i, b: saved.get(i),
                save=lambda i, b, value: saved.__setitem__(i, value),
                on_progress=lambda *args: None, check_cancelled=lambda: None)
    with pytest.raises(ValueError, match='failed'):
        analyze_batches([10, 11, 12], complete, **args)
    assert saved == {0: 10, 2: 12}
    retried = []
    result = analyze_batches([10, 11, 12],
                             lambda i, b: retried.append(i) or b, **args)
    assert result == [10, 11, 12]
    assert retried == [1]


def test_cancelled_does_not_call_provider_or_publish():
    def cancelled():
        raise RuntimeError('cancelled')

    def unexpected(*args):
        pytest.fail('cancelled work must not run')

    with pytest.raises(RuntimeError, match='cancelled'):
        analyze_batches([1], unexpected, load=unexpected, save=unexpected,
                        on_progress=unexpected, check_cancelled=cancelled)


def test_cancel_during_requests_stops_queue_and_discards_late_results():
    released = Event()
    cancelled = False
    called, saved = [], []

    def complete(index, batch):
        called.append(index)
        assert released.wait(3)
        return batch

    def check():
        if cancelled:
            raise RuntimeError('cancelled')

    def publish(done, total, active):
        nonlocal cancelled
        if len(active) == 3:
            cancelled = True
            released.set()

    with pytest.raises(RuntimeError, match='cancelled'):
        analyze_batches(list(range(10)), complete, load=lambda *args: None,
                        save=lambda *args: saved.append(args), on_progress=publish,
                        check_cancelled=check)
    assert len(called) <= 3
    assert saved == []
