"""Run ONLY inside remote GDB. Interrupt after two seconds and collect all stacks."""
import gdb
import os
import signal
import threading
gdb.execute('set pagination off')
gdb.execute('set confirm off')
timer = threading.Timer(2, lambda: os.kill(os.getpid(), signal.SIGINT))
timer.start()
try:
    gdb.execute('run')
except (gdb.error, KeyboardInterrupt):
    pass
finally:
    timer.cancel()
gdb.execute('thread apply all bt')
gdb.execute('kill')
