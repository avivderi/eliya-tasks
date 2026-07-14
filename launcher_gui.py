"""
One-click GUI launcher for the Xiaomi -> Google Keep migration toolkit.

Runs entirely on the Python standard library (tkinter + subprocess), so
there is nothing extra to install beyond the requirements.txt already
needed for xiaomi_export.py / keep_import.py. Works the same way on
macOS and Ubuntu.

Each button runs the matching script as a subprocess and streams its
console output live into the log box below, so you always see exactly
what the underlying script is doing (including the "press Enter to
continue after logging in" prompts -- those are handled by extra
"I've logged in" buttons that send Enter to the running process).
"""

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import scrolledtext, messagebox

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PYTHON = sys.executable  # use whichever interpreter launched this GUI (the venv one)


class ScriptRunner:
    """Runs one script as a subprocess and pipes its stdout into a queue."""

    def __init__(self, script_name, extra_args=None):
        self.script_path = os.path.join(BASE_DIR, script_name)
        self.extra_args = extra_args or []
        self.process = None
        self.output_queue = queue.Queue()
        self.thread = None

    def is_running(self):
        return self.process is not None and self.process.poll() is None

    def start(self):
        if self.is_running():
            return
        self.process = subprocess.Popen(
            [PYTHON, self.script_path, *self.extra_args],
            cwd=BASE_DIR,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        self.thread = threading.Thread(target=self._pump_output, daemon=True)
        self.thread.start()

    def _pump_output(self):
        for line in self.process.stdout:
            self.output_queue.put(line)
        self.output_queue.put(f"\n[process exited with code {self.process.returncode}]\n")

    def send_enter(self):
        """Used to answer the script's 'press Enter to continue' prompt after manual login."""
        if self.is_running():
            try:
                self.process.stdin.write("\n")
                self.process.stdin.flush()
            except (BrokenPipeError, OSError):
                pass

    def stop(self):
        if self.is_running():
            self.process.terminate()


class MigrationGUI:
    def __init__(self, root):
        self.root = root
        root.title("Xiaomi Notes -> Google Keep Migration")
        root.geometry("820x560")

        tk.Label(
            root,
            text="Xiaomi Notes -> Google Keep Migration Tool",
            font=("Helvetica", 15, "bold"),
        ).pack(pady=(10, 0))
        tk.Label(
            root,
            text="Step 1 backs up your Xiaomi notes to a local file. "
                 "Step 2 uploads that file into Google Keep.",
            font=("Helvetica", 10),
        ).pack(pady=(0, 10))

        button_frame = tk.Frame(root)
        button_frame.pack(pady=5)

        self.step1_runner = ScriptRunner("xiaomi_export.py")
        self.step2_runner = ScriptRunner("keep_import.py")

        tk.Button(
            button_frame, text="1) Extract from Xiaomi Cloud", width=28,
            command=lambda: self.run_step(self.step1_runner, "Xiaomi extraction"),
        ).grid(row=0, column=0, padx=5, pady=5)

        tk.Button(
            button_frame, text="I've logged in to Xiaomi -> Continue", width=28,
            command=lambda: self.step1_runner.send_enter(),
        ).grid(row=0, column=1, padx=5, pady=5)

        tk.Button(
            button_frame, text="2) Import into Google Keep", width=28,
            command=lambda: self.run_step(self.step2_runner, "Google Keep import"),
        ).grid(row=1, column=0, padx=5, pady=5)

        tk.Button(
            button_frame, text="I've logged in to Google -> Continue", width=28,
            command=lambda: self.step2_runner.send_enter(),
        ).grid(row=1, column=1, padx=5, pady=5)

        tk.Button(
            button_frame, text="Selector Calibration (Xiaomi --inspect)", width=28,
            command=lambda: self.run_step(
                ScriptRunner("xiaomi_export.py", ["--inspect"]), "Xiaomi calibration"),
        ).grid(row=2, column=0, padx=5, pady=5)

        tk.Button(
            button_frame, text="Selector Calibration (Keep --inspect)", width=28,
            command=lambda: self.run_step(
                ScriptRunner("keep_import.py", ["--inspect"]), "Keep calibration"),
        ).grid(row=2, column=1, padx=5, pady=5)

        tk.Label(root, text="Log output:", font=("Helvetica", 10, "bold")).pack(
            anchor="w", padx=10)
        self.log_box = scrolledtext.ScrolledText(root, height=24, font=("Courier", 9))
        self.log_box.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        self.active_runner = None
        self.root.after(150, self._poll_output)

    def run_step(self, runner, label):
        if self.active_runner and self.active_runner.is_running():
            messagebox.showwarning(
                "Already running",
                "Another step is already running. Wait for it to finish first.",
            )
            return
        self.log_box.insert(tk.END, f"\n=== Starting: {label} ===\n")
        self.log_box.see(tk.END)
        self.active_runner = runner
        runner.start()

    def _poll_output(self):
        if self.active_runner:
            try:
                while True:
                    line = self.active_runner.output_queue.get_nowait()
                    self.log_box.insert(tk.END, line)
                    self.log_box.see(tk.END)
            except queue.Empty:
                pass
        self.root.after(150, self._poll_output)


def main():
    root = tk.Tk()
    MigrationGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
