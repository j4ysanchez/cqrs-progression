import queue
import threading
from collections import defaultdict


class MessageBus:
    def __init__(self):
        self._queue = queue.Queue()
        self._subscribers: dict[type, list[callable]] = defaultdict(list)
        self._thread: threading.Thread | None = None
        self._running = False

    def subscribe(self, event_type: type, handler: callable) -> None:
        """Register a handler to be called when event_type is published."""
        self._subscribers[event_type].append(handler)

    def publish(self, event) -> None:
        """Put an event on the queue. Returns immediately."""
        self._queue.put(event)

    def start(self) -> None:
        """Start the background processing thread."""
        self._running = True
        # set thread to daemon so python will kill the thread when the main program exits
        self._thread = threading.Thread(target=self._process, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Signal the thread to stop and wait for it to finish."""
        self._running = False
        self._queue.put(None)  # sentinel value (not real data) to unblock the thread
        self._thread.join() # make main thread wait until background therad has fully exited

    def flush(self) -> None:
        """Block until all currently queued events have been processed.
        Use this in tests and demos before querying the read model."""
        self._queue.join()

    def _process(self) -> None:
        while self._running:
            # block=True means this thread will wait here until an event is available in the queue 
            # before continuing. This is more efficient than busy-waiting. (see os synchronization primitives for more details)
            event = self._queue.get(block=True)
            if event is None:
                self._queue.task_done()
                break
            for handler in self._subscribers[type(event)]:
                try:
                    handler(event)
                except Exception as e:
                    # In production: dead-letter queue, retry logic, alerting.
                    # Here: log and continue — one bad handler does not stop others.
                    print(f"[BUS ERROR] Handler {handler.__name__} failed: {e}")
            self._queue.task_done()
