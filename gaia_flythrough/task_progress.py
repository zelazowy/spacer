"""Structured per-stage progress; negative totals mean genuinely unknown work."""
import time


class Diagnostic(str):
    """Detailed log text which must not replace the concise current stage."""
    detail=True


class StageProgress:
    def __init__(self,label,total,callback=None,progress=None,cancel=None):
        self.label,self.total,self.callback,self.cancel=label,total,callback,cancel
        self.started=time.monotonic();self.last_emit=self.started;self.done=0
        self.check_cancel()
        if progress: progress(label+'…')
        self.emit()

    def check_cancel(self):
        if self.cancel is not None and self.cancel.is_set():
            raise InterruptedError('Processing cancelled; completed preparation is kept.')

    def emit(self):
        now=time.monotonic()
        if self.callback: self.callback(self.label,self.done,self.total,now-self.started)
        self.last_emit=now

    def update(self,done,force=False):
        self.check_cancel();self.done=done
        if force or done==1 or done==self.total or time.monotonic()-self.last_emit>=.25: self.emit()

    def set_total(self,total):
        self.check_cancel();self.total=total;self.emit()

    def track(self,items):
        # Updating after yield counts completed work, including deferred/skipped
        # entries, but never counts an item which raises or is cancelled.
        for index,item in enumerate(items,1):
            self.check_cancel()
            yield item
            self.update(index)
