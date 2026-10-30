from contextvars import ContextVar

progress_sink = ContextVar('concurrency_progress', default=None)


def campaign_progress(completed, required):
    sink = progress_sink.get()
    if sink:
        sink({'completed': completed, 'required': required})
