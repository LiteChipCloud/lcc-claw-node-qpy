import utime

try:
    import _thread
except Exception:
    _thread = None


def _sleep_ms(delay_ms):
    if delay_ms <= 0:
        delay_ms = 1
    if hasattr(utime, "sleep_ms"):
        utime.sleep_ms(delay_ms)
        return
    utime.sleep(float(delay_ms) / 1000.0)


class CommandWorker(object):

    def __init__(self, runner, state):
        self.runner = runner
        self.state = state
        self.available = bool(_thread) and hasattr(_thread, "start_new_thread")
        self._lock = _thread.allocate_lock() if bool(_thread) and hasattr(_thread, "allocate_lock") else None
        self._pending_cmd = None
        self._result = None
        self._executing = False
        self._started = False
        self.state.note_worker_status(self.available, False)
        if self.available:
            self._start()

    def _acquire(self):
        if self._lock is not None:
            self._lock.acquire()

    def _release(self):
        if self._lock is not None:
            self._lock.release()

    def _start(self):
        if self._started:
            return
        _thread.start_new_thread(self._run_forever, ())
        self._started = True

    def can_accept(self):
        self._acquire()
        try:
            return self._pending_cmd is None and self._result is None and (not self._executing)
        finally:
            self._release()

    def submit(self, cmd):
        if (not self.available) or (not cmd):
            return False
        accepted = False
        self._acquire()
        try:
            if self._pending_cmd is None and self._result is None and (not self._executing):
                self._pending_cmd = cmd
                accepted = True
        finally:
            self._release()
        if accepted:
            self.state.note_inflight_start(cmd.get("request_id"), cmd.get("tool"))
            self.state.note_worker_status(self.available, True)
        return accepted

    def poll_result(self):
        self._acquire()
        try:
            item = self._result
            self._result = None
            busy = self._pending_cmd is not None or self._executing or self._result is not None
        finally:
            self._release()
        self.state.note_worker_status(self.available, busy)
        return item

    def _build_worker_error(self, cmd, message):
        return {
            "cmd_id": cmd.get("request_id", ""),
            "requested_tool": cmd.get("tool", ""),
            "tool": cmd.get("tool", ""),
            "status": "failed",
            "result_code": "EXEC_RUNTIME_ERROR",
            "data": None,
            "error": message,
            "duration_ms": 0,
        }

    def _run_forever(self):
        while True:
            cmd = None
            self._acquire()
            try:
                if self._pending_cmd is not None and self._result is None and (not self._executing):
                    cmd = self._pending_cmd
                    self._pending_cmd = None
                    self._executing = True
            finally:
                self._release()

            if cmd is None:
                _sleep_ms(20)
                continue

            try:
                result = self.runner.execute(cmd)
            except Exception as e:
                self.state.note_error("WORKER_EXEC_FAILED", str(e))
                result = self._build_worker_error(cmd, str(e))

            self._acquire()
            try:
                self._result = {
                    "cmd": cmd,
                    "result": result,
                }
                self._executing = False
                busy = self._pending_cmd is not None or self._result is not None
            finally:
                self._release()

            self.state.note_inflight_finish(result.get("status"), result.get("result_code"))
            self.state.note_worker_status(self.available, busy)
