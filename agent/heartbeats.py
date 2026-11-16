"""Heartbeats — Sistema 2 background monitoring without a model in the loop.

A small in-process scheduler: jobs are callables registered with an interval;
a daemon thread wakes every second and runs whatever is due. Nothing is
registered by default — autonomous work needs explicit registration (opt-in),
and jobs that act on the world should use the tool registry's confirmation
gates, not this scheduler, for anything destructive.
"""
from __future__ import annotations

import threading
import time
import traceback
from dataclasses import dataclass, field


@dataclass
class Job:
    name: str
    interval_seconds: float
    func: object
    last_run: float | None = None
    run_count: int = 0
    last_error: str | None = None
    enabled: bool = True


class Heartbeat:
    def __init__(self):
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def register(self, name, interval_seconds, func, *, enabled=True):
        if not name or not callable(func) or not interval_seconds or interval_seconds < 1:
            raise ValueError('Nombre, función e intervalo ≥ 1s obligatorios.')
        with self._lock:
            self._jobs[name] = Job(name=name, interval_seconds=float(interval_seconds), func=func, enabled=bool(enabled))

    def unregister(self, name):
        with self._lock:
            self._jobs.pop(name, None)

    def set_enabled(self, name, enabled):
        with self._lock:
            if name in self._jobs:
                self._jobs[name].enabled = bool(enabled)

    def run_due(self, now=None):
        """Run every job whose interval elapsed; returns what ran (also for tests)."""
        now = now or time.time()
        ran = []
        with self._lock:
            due = [job for job in self._jobs.values()
                   if job.enabled and (job.last_run is None or now - job.last_run >= job.interval_seconds)]
        for job in due:
            try:
                job.func()
                job.last_error = None
            except Exception:
                job.last_error = traceback.format_exc(limit=2)
            job.last_run, job.run_count = now, job.run_count + 1
            ran.append(job.name)
        return ran

    def start(self, tick_seconds=1.0):
        if self._thread and self._thread.is_alive():
            return

        def loop():
            while not self._stop.is_set():
                self.run_due()
                self._stop.wait(tick_seconds)

        self._stop.clear()
        self._thread = threading.Thread(target=loop, name='JARVIS heartbeats', daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    def status(self):
        with self._lock:
            return [{'name': job.name, 'interval_seconds': job.interval_seconds,
                     'enabled': job.enabled, 'run_count': job.run_count,
                     'last_run': job.last_run, 'last_error': job.last_error}
                    for job in self._jobs.values()]
