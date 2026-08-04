import os
import json
import signal

class ProcessManager:
    """
    Manages process PIDs, mode files, and state files for background service daemons.
    """

    def __init__(self, pid_file, mode_file=None, state_file=None):
        self.pid_file = pid_file
        self.mode_file = mode_file
        self.state_file = state_file

    def is_running(self):
        """Checks if process identified by pid_file is currently running."""
        if not os.path.exists(self.pid_file):
            return False, None
        try:
            with open(self.pid_file, 'r', encoding='utf-8') as f:
                pid = int(f.read().strip())
            # Signal 0 tests process existence
            os.kill(pid, 0)
            return True, pid
        except (ValueError, OSError):
            self.cleanup_pid()
            return False, None

    def save_pid(self, pid):
        """Saves PID to PID file."""
        with open(self.pid_file, 'w', encoding='utf-8') as f:
            f.write(str(pid))

    def cleanup_pid(self):
        """Removes PID file if it exists."""
        if os.path.exists(self.pid_file):
            try:
                os.remove(self.pid_file)
            except OSError:
                pass

    def get_mode(self, default='real'):
        """Reads active process mode."""
        if self.mode_file and os.path.exists(self.mode_file):
            try:
                with open(self.mode_file, 'r', encoding='utf-8') as f:
                    return f.read().strip()
            except Exception:
                pass
        return default

    def set_mode(self, mode):
        """Writes process mode."""
        if self.mode_file:
            with open(self.mode_file, 'w', encoding='utf-8') as f:
                f.write(str(mode))

    def get_desired_state(self):
        """Reads desired state dictionary."""
        if self.state_file and os.path.exists(self.state_file):
            try:
                with open(self.state_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def set_desired_state(self, state_dict):
        """Writes desired state dictionary."""
        if self.state_file:
            with open(self.state_file, 'w', encoding='utf-8') as f:
                json.dump(state_dict, f, indent=2)

    def stop_process(self):
        """Sends SIGTERM signal to process if running."""
        running, pid = self.is_running()
        if running and pid:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
            self.cleanup_pid()
            return True
        return False
