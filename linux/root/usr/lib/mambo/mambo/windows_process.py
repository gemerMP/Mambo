"""Signal a child console from a short-lived process; leave Lite's console alone."""
import ctypes
import subprocess
import sys


def signal_console(pid):
    kernel = ctypes.windll.kernel32
    kernel.FreeConsole()
    if not kernel.AttachConsole(int(pid)):
        return 1
    # Ignore Ctrl+C in this helper; CTRL_BREAK targets the attached console.
    kernel.SetConsoleCtrlHandler(None, True)
    sent = kernel.GenerateConsoleCtrlEvent(1, 0)
    kernel.FreeConsole()
    return 0 if sent else 1


def stop_console_process(process):
    if getattr(sys, 'frozen', False):
        command = [sys.executable, '--signal-console', str(process.pid)]
    else:
        command = [sys.executable, '-m', 'mambo.windows_process', str(process.pid)]
    try:
        subprocess.run(command, timeout=3, creationflags=subprocess.CREATE_NO_WINDOW,
                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        process.wait(timeout=8)
    except (subprocess.TimeoutExpired, OSError):
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)


if __name__ == '__main__':
    sys.exit(signal_console(sys.argv[1]))

class ChildJob:
    """Windows closes children if the owning Mambo process crashes/exits."""
    def __init__(self, process):
        from ctypes import wintypes as w
        class Basic(ctypes.Structure):
            _fields_ = [('process_time', ctypes.c_longlong), ('job_time', ctypes.c_longlong),
                        ('flags', w.DWORD), ('min_ws', ctypes.c_size_t), ('max_ws', ctypes.c_size_t),
                        ('active', w.DWORD), ('affinity', ctypes.c_size_t), ('priority', w.DWORD), ('scheduling', w.DWORD)]
        class IO(ctypes.Structure):
            _fields_ = [(name, ctypes.c_ulonglong) for name in ('read_ops','write_ops','other_ops','read_bytes','write_bytes','other_bytes')]
        class Extended(ctypes.Structure):
            _fields_ = [('basic', Basic), ('io', IO), ('process_memory', ctypes.c_size_t),
                        ('job_memory', ctypes.c_size_t), ('peak_process', ctypes.c_size_t), ('peak_job', ctypes.c_size_t)]
        k = ctypes.WinDLL('kernel32', use_last_error=True)
        k.CreateJobObjectW.argtypes = [ctypes.c_void_p, w.LPCWSTR]
        k.CreateJobObjectW.restype = w.HANDLE
        k.SetInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]
        k.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
        k.CloseHandle.argtypes = [w.HANDLE]
        self.kernel = k
        self.handle = k.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = Extended()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not k.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)) or not k.AssignProcessToJobObject(self.handle, int(process._handle)):
            error = ctypes.get_last_error()
            self.close()
            raise ctypes.WinError(error)

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None
