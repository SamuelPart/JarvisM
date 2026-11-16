"""Minimum display time for a successful desktop weather search."""
import time


class WeatherLoadingTiming:
    def __init__(self, duration=3.0, clock=time.monotonic, sleep=time.sleep):
        self.duration = duration
        self.clock = clock
        self.sleep = sleep
        self.started = None

    def wait_for_event(self, event):
        if event == 'loading':
            self.started = self.clock()
        elif event == 'result' and self.started is not None:
            remaining = self.duration - (self.clock() - self.started)
            self.started = None
            if remaining > 0:
                self.sleep(remaining)
        elif event == 'error':
            self.started = None
