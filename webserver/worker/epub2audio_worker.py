#!/usr/bin/env python3
"""
EPUB to Audio Worker - Convert EPUB books to audiobooks with progress tracking
"""

import logging
import subprocess
import threading
import time
import os
import signal
import sys
import json
import re
from typing import Optional, Dict, Any

"""
python3 main.py --tts edge --language zh-CN --worker_count 2 --voice_name zh-CN-YunyangNeural --no_prompt
 test.epub ./epub_to_audio/
"""


def remove_null_values(obj):
    if isinstance(obj, dict):
        return {k: remove_null_values(v) for k, v in obj.items() if v is not None}
    elif isinstance(obj, list):
        return [remove_null_values(item) for item in obj if item is not None]
    else:
        return obj


def json_dumps_clean(obj, **kwargs):
    cleaned_obj = remove_null_values(obj)
    return json.dumps(cleaned_obj, **kwargs)


class EpubToAudioWorker:
    """
    Specialized worker for epub_to_audio conversion with progress tracking
    """
    STATUS_PROCESSING = "processing"
    STATUS_CONVERTED = "converted"
    STATUS_FAILED = "failed"

    def __init__(self, main_py_path: str = None, timeout: Optional[float] = None):
        """
        Initialize the EpubToAudioWorker
        """
        self.main_py_path = main_py_path or "webserver/epub_to_audio/main.py"
        self.timeout = timeout
        self.process = None
        self.progress_data = {
            "status": self.STATUS_PROCESSING,
            "total_chapters": 0,
            "total_characters": 0,
            "processed_chapters": 0,
            "converted_chapters": 0,
            "failed_chapters": 0,
            "current_chapter": None,
            "chapters": {},  # {idx: {"title": str, "status": str, "error": str}}
            "output_folder": None,
            "error_message": None,
            "start_time": None,
            "end_time": None,
            "execution_time": 0
        }

    def _parse_bookbarn_log(self, line: str):
        """
        Parse BOOKBARN log messages and update progress
        """
        if "[BOOKBARN]" not in line:
            # logging.info(f"[LOG] {line}")
            return

        match = re.search(r'\[BOOKBARN\](.+)', line)
        if not match:
            return

        message = match.group(1)

        # Parse different types of messages
        if message.startswith("Chapters:"):
            # Total chapters count
            match = re.search(r'Chapters:(\d+)', message)
            if match:
                self.progress_data["total_chapters"] = int(match.group(1))
        elif message.startswith("Total characters:"):
            match = re.search(r'Total characters:(\d+)', message)
            if match:
                self.progress_data["total_characters"] = int(match.group(1))
        elif message.startswith("Processing:"):
            # Currently processing chapter
            match = re.search(r'Processing:(\d+),(.+)', message)
            if match:
                idx = int(match.group(1))
                title = match.group(2)
                self.progress_data["current_chapter"] = {"idx": idx, "title": title}
                self.progress_data["chapters"][idx] = {
                    "title": title,
                    "status": self.STATUS_PROCESSING,
                    "error": None
                }
                self.progress_data["processed_chapters"] = len([
                    ch for ch in self.progress_data["chapters"].values()
                    if ch["status"] in [self.STATUS_PROCESSING, self.STATUS_CONVERTED, self.STATUS_FAILED]
                ])

        elif message.startswith("Converted:"):
            match = re.search(r'Converted:(\d+),(.+)', message)
            if match:
                idx = int(match.group(1))
                title = match.group(2)
                if idx in self.progress_data["chapters"]:
                    self.progress_data["chapters"][idx]["status"] = self.STATUS_CONVERTED
                else:
                    self.progress_data["chapters"][idx] = {
                        "title": title,
                        "status": self.STATUS_CONVERTED,
                        "error": None
                    }
                self.progress_data["converted_chapters"] = len([
                    ch for ch in self.progress_data["chapters"].values()
                    if ch["status"] == self.STATUS_CONVERTED
                ])

        elif message.startswith("Error:"):
            match = re.search(r'Error:(\d+),(.+)', message)
            if match:
                idx = int(match.group(1))
                error = match.group(2)
                if idx in self.progress_data["chapters"]:
                    self.progress_data["chapters"][idx]["status"] = self.STATUS_FAILED
                    self.progress_data["chapters"][idx]["error"] = error
                else:
                    self.progress_data["chapters"][idx] = {
                        "title": f"Chapter {idx}",
                        "status": self.STATUS_FAILED,
                        "error": error
                    }
                self.progress_data["failed_chapters"] = len([
                    ch for ch in self.progress_data["chapters"].values()
                    if ch["status"] == self.STATUS_FAILED
                ])

        elif message.startswith("ConversionFailed:"):
            match = re.search(r'ConversionFailed:(\d+)', message)
            if match:
                failed_count = int(match.group(1))
                self.progress_data["status"] = self.STATUS_FAILED
                self.progress_data["failed_chapters"] = failed_count
                self.progress_data["end_time"] = int(time.time())

        elif message.startswith("ConversionSuccess:"):
            match = re.search(r'ConversionSuccess:(.+)', message)
            if match:
                output_folder = match.group(1)
                self.progress_data["status"] = self.STATUS_CONVERTED
                self.progress_data["output_folder"] = output_folder
                self.progress_data["end_time"] = int(time.time())

        else:
            logging.info(f"log message: {message}")

    def _read_stream_with_progress(self, stream, data_list, show_output=True):
        """
        Read from stream and parse progress information
        """
        try:
            for line in iter(stream.readline, b''):
                if line:
                    decoded_line = line.decode('utf-8', errors='replace').rstrip()
                    data_list.append(decoded_line)
                    self._parse_bookbarn_log(decoded_line)

                    if show_output:
                        print(f"[OUTPUT] {decoded_line}")
                    elif "[BOOKBARN]" in decoded_line:
                        print(f"[BOOKBARN_LOG] {decoded_line}")
        except Exception as e:
            print(f"[ERROR] Error reading stream: {e}")
        finally:
            stream.close()

    def convert_epub_to_audio(self, epub_path: str, output_dir: str,
                              tts: str = "edge", language: str = "zh-CN",
                              worker_count: int = 2, voice_name: str = "zh-CN-YunyangNeural",
                              no_prompt: bool = True, show_output: bool = True, proxy: str = None, **kwargs) -> Dict[str, Any]:
        """
        Convert EPUB to audio using epub_to_audio

        Args:
            epub_path: Path to the EPUB file
            output_dir: Output directory for audio files
            tts: TTS provider (default: edge)
            language: Language code (default: zh-CN)
            worker_count: Number of workers (default: 2)
            voice_name: Voice name (default: zh-CN-YunyangNeural)
            no_prompt: Skip prompts (default: True)
            show_output: Show detailed output (default: True)
            **kwargs: Additional arguments

        Returns:
            Dictionary containing conversion results and progress
        """
        # Reset progress data
        self.progress_data = {
            "status": self.STATUS_PROCESSING,
            "total_chapters": 0,
            "processed_chapters": 0,
            "converted_chapters": 0,
            "failed_chapters": 0,
            "current_chapter": -1,
            "chapters": {},
            "output_folder": '',
            "error_message": '',
            "start_time": int(time.time()),
            "end_time": 0,
            "execution_time": 0
        }

        # Build command
        cmd = [
            "python3", self.main_py_path,
            "--tts", tts,
            "--language", language,
            "--worker_count", str(worker_count),
            "--voice_name", voice_name,
        ]

        if no_prompt:
            cmd.append("--no_prompt")

        # Add additional kwargs
        for key, value in kwargs.items():
            if key.startswith("--"):
                cmd.extend([key, str(value)])
            elif not key.startswith("-"):
                cmd.extend([f"--{key}", str(value)])

        if proxy:
            cmd.extend(["--proxy", proxy])

        # Add input and output paths
        cmd.extend([epub_path, output_dir])

        stdout_data = []
        stderr_data = []

        try:
            logging.info(f"[INFO] Starting EPUB to Audio conversion: {' '.join(cmd)}")

            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                preexec_fn=os.setsid if os.name != 'nt' else None
            )

            stdout_thread = threading.Thread(
                target=self._read_stream_with_progress,
                args=(self.process.stdout, stdout_data, show_output)
            )
            stderr_thread = threading.Thread(
                target=self._read_stream_with_progress,
                args=(self.process.stderr, stderr_data, show_output)
            )

            stdout_thread.start()
            stderr_thread.start()

            # Wait for process completion or timeout
            try:
                return_code = self.process.wait(timeout=self.timeout)
                logging.info(f"[INFO] Conversion completed with return code: {return_code}")

            except subprocess.TimeoutExpired:
                logging.warning(f"[WARNING] Conversion timed out after {self.timeout} seconds")
                self._kill_process()
                return_code = -9  # SIGKILL
                self.progress_data["status"] = self.STATUS_FAILED
                self.progress_data["error_message"] = f"Conversion timed out after {self.timeout} seconds"
            except KeyboardInterrupt:
                logging.info("[INFO] Conversion interrupted by user (Ctrl+C)")
                self._kill_process()
                return_code = -2  # Interrupted
                self.progress_data["status"] = self.STATUS_FAILED
                self.progress_data["error_message"] = "Conversion interrupted by user"
                # Re-raise the exception to be handled by outer try-catch
                raise

            stdout_thread.join(timeout=1)
            stderr_thread.join(timeout=1)

            if self.progress_data["end_time"] is None:
                self.progress_data["end_time"] = int(time.time())

            self.progress_data["execution_time"] = self.progress_data["end_time"] - self.progress_data["start_time"]

            if self.progress_data["status"] == self.STATUS_PROCESSING:
                if return_code == 0:
                    self.progress_data["status"] = self.STATUS_CONVERTED
                else:
                    self.progress_data["status"] = self.STATUS_FAILED
                    self.progress_data["error_message"] = f"Process exited with code {return_code}"

            success = return_code == 0 and self.progress_data["status"] == self.STATUS_CONVERTED

            return {
                'success': success,
                'stdout': stdout_data,
                'stderr': stderr_data,
                'return_code': return_code,
                'progress': self.progress_data,
                'status': self.progress_data["status"],
                'error': None if success else (self.progress_data["error_message"] or f"Exited code {return_code}")
            }

        except KeyboardInterrupt:
            # Handle Ctrl+C interruption
            logging.info("[INFO] Conversion process interrupted by user")
            if self.progress_data["end_time"] is None:
                self.progress_data["end_time"] = int(time.time())
            self.progress_data["execution_time"] = self.progress_data["end_time"] - self.progress_data["start_time"]
            self.progress_data["status"] = self.STATUS_FAILED
            self.progress_data["error_message"] = "Process interrupted by user"

            # Ensure process is killed
            self._kill_process()

            return {
                'success': False,
                'error': 'Process interrupted by user',
                'stdout': stdout_data,
                'stderr': stderr_data,
                'return_code': -2,
                'progress': self.progress_data,
                'status': self.progress_data["status"],
            }

        except Exception as e:
            if self.progress_data["end_time"] is None:
                self.progress_data["end_time"] = int(time.time())
            self.progress_data["execution_time"] = self.progress_data["end_time"] - self.progress_data["start_time"]
            self.progress_data["status"] = self.STATUS_FAILED
            self.progress_data["error_message"] = str(e)

            error_msg = f"Failed to execute conversion: {str(e)}"
            logging.error(f"[ERROR] {error_msg}")

            return {
                'success': False,
                'error': error_msg,
                'stdout': stdout_data,
                'stderr': stderr_data,
                'return_code': -1,
                'progress': self.progress_data
            }

    def get_progress(self) -> Dict[str, Any]:
        """
        Get current progress as JSON

        Returns:
            Progress data dictionary
        """
        if self.progress_data["status"] == self.STATUS_PROCESSING and self.progress_data["start_time"]:
            self.progress_data["execution_time"] = int(time.time()) - self.progress_data["start_time"]

        return self.progress_data.copy()

    def get_progress_json(self) -> str:
        """
        Get current progress as JSON string

        Returns:
            JSON string representation of progress
        """
        return json_dumps_clean(self.get_progress(), indent=2, ensure_ascii=False)

    def _kill_process(self):
        """
        Kill the running process and its children.
        """
        if self.process and self.process.poll() is None:
            try:
                if os.name == 'nt':  # Windows
                    self.process.terminate()
                else:  # Unix-like systems
                    # Kill the process group to ensure child processes are also killed
                    os.killpg(os.getpgid(self.process.pid), signal.SIGTERM)
                    time.sleep(0.5)  # Give it time to terminate gracefully

                    # Force kill if still running
                    if self.process.poll() is None:
                        os.killpg(os.getpgid(self.process.pid), signal.SIGKILL)

            except Exception as e:
                print(f"[ERROR] Failed to kill process: {e}")

    def is_running(self) -> bool:
        """
        Check if the conversion process is still running.

        Returns:
            True if process is running, False otherwise
        """
        return self.process is not None and self.process.poll() is None

    def is_completed(self) -> bool:
        """
        Check if the conversion process has completed successfully.

        Returns:
            True if process is completed, False otherwise
        """
        return self.progress_data["status"] == self.STATUS_CONVERTED

    def get_status(self) -> str:
        """
        Get the current status of the conversion process.

        Returns:
            Current status as a string
        """
        return self.progress_data["status"]

    def stop(self):
        """
        Stop the currently running conversion process.
        """
        if self.is_running():
            logging.info("[INFO] Stopping conversion process...")
            self._kill_process()
            self.progress_data["status"] = self.STATUS_FAILED
            self.progress_data["error_message"] = "Process stopped by user"
            if self.progress_data["end_time"] is None:
                self.progress_data["end_time"] = int(time.time())
                self.progress_data["execution_time"] = self.progress_data["end_time"] - self.progress_data["start_time"]


def main():
    """
    EPUB to Audio conversion worker
    """
    if len(sys.argv) < 2:
        print("Usage:")
        print("  EPUB to Audio conversion:")
        print("    python simple_worker.py <epub_path> <output_dir> [options]")
        print("    Example: python simple_worker.py /path/to/book.epub /path/to/output")
        print("    Options:")
        print("      --tts <provider>           TTS provider (default: edge)")
        print("      --language <code>          Language code (default: zh-CN)")
        print("      --worker_count <num>       Number of workers (default: 2)")
        print("      --voice_name <name>        Voice name (default: zh-CN-YunyangNeural)")
        print("      --main_py_path <path>      Path to main.py (default: epub_to_audio/main.py)")
        print("      --timeout <seconds>        Conversion timeout")
        print("      --progress_only            Only show progress, don't show full output")
        return

    # Handle EPUB to Audio conversion
    if len(sys.argv) < 3:
        print("Error: epub_to_audio requires <epub_path> and <output_dir>")
        print("Usage: python simple_worker.py <epub_path> <output_dir> [options]")
        return

    epub_path = sys.argv[1]
    output_dir = sys.argv[2]

    # Parse additional options
    options = {}
    progress_only = False
    i = 3  # Start from the third argument (after epub_path and output_dir)
    while i < len(sys.argv):
        arg = sys.argv[i]
        if arg == "--progress_only":
            progress_only = True
            i += 1
        elif arg.startswith("--") and i + 1 < len(sys.argv):
            key = arg[2:]  # Remove --
            value = sys.argv[i + 1]
            if key in ["worker_count", "timeout"]:
                try:
                    value = int(value) if key == "worker_count" else float(value)
                except ValueError:
                    pass
            options[key] = value
            i += 2
        else:
            i += 1

    # Extract special options
    main_py_path = options.pop("main_py_path", "webserver/epub_to_audio/main.py")
    timeout = options.pop("timeout", None)

    # Create EPUB to Audio worker
    worker = EpubToAudioWorker(main_py_path=main_py_path, timeout=timeout)

    print("[INFO] Starting EPUB to Audio conversion")
    print(f"[INFO] EPUB: {epub_path}")
    print(f"[INFO] Output: {output_dir}")
    print(f"[INFO] Progress only mode: {progress_only}")
    if options:
        print(f"[INFO] Options: {options}")

    if not os.path.exists(epub_path):
        print(f"[ERROR] EPUB file does not exist: {epub_path}")
        print("Please modify the script to use a valid epub_path")
        return

    if not os.path.exists(output_dir):
        print(f"[INFO] Creating output directory: {output_dir}")
        os.makedirs(output_dir, exist_ok=True)

    # Start conversion in a separate thread if progress_only is enabled
    if progress_only:
        print("[INFO] Running in progress monitoring mode...")
        import threading

        def conversion_thread():
            return worker.convert_epub_to_audio(epub_path, output_dir, show_output=False, **options)

        # Start conversion in background
        thread = threading.Thread(target=conversion_thread)
        thread.daemon = True
        thread.start()

        # Monitor progress
        try:
            while thread.is_alive() or worker.is_running():
                progress = worker.get_progress()
                print(f"\n[PROGRESS] {json_dumps_clean(progress, indent=2, ensure_ascii=False)}")
                time.sleep(15)  # Update every 2 seconds

            # Get final progress
            final_progress = worker.get_progress()
            print(f"\n[FINAL] {json_dumps_clean(final_progress, indent=2, ensure_ascii=False)}")

        except KeyboardInterrupt:
            print("\n[INFO] Stopping conversion...")
            worker.stop()

    else:
        print("[INFO] Running in full output mode...")
        try:
            # Execute conversion and show full results
            result = worker.convert_epub_to_audio(epub_path, output_dir, **options)

            # Print results
            print("\n" + "=" * 50)
            print("CONVERSION RESULTS")
            print("=" * 50)
            print(f"Success: {result['success']}")
            print(f"Return Code: {result['return_code']}")

            if result['error']:
                print(f"Error: {result['error']}")

            # Print progress information as JSON
            print("\nPROGRESS DATA:")
            print(json_dumps_clean(result['progress'], indent=2, ensure_ascii=False))

            if result['stderr']:
                print("\nSTDERR:")
                for line in result['stderr']:
                    print(f"  {line}")

        except KeyboardInterrupt:
            print("\n[INFO] Conversion interrupted by user")
            if worker.is_running():
                print("[INFO] Stopping conversion process...")
                worker.stop()
            print("[INFO] Conversion stopped")


if __name__ == "__main__":
    main()
