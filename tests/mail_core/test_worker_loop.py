import threading
import time

from mail_core.worker import main as worker_main


def test_worker_stops_on_flag():
    def run():
        worker_main.run(poll_interval_s=0.05)

    t = threading.Thread(target=run, daemon=True)
    t.start()
    time.sleep(0.12)
    worker_main.request_stop()
    t.join(timeout=2)
    assert not t.is_alive()
