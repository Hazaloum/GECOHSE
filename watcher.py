import os
import time
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import hse_bot

WATCH_DIR = os.path.join(os.path.dirname(__file__), "input")


class ExcelHandler(FileSystemEventHandler):

    def on_created(self, event):
        self._handle(event.src_path)

    def on_moved(self, event):
        self._handle(event.dest_path)

    def _handle(self, path):
        filename = os.path.basename(path)
        # Ignore temp files (Excel creates ~$ files while saving)
        if not filename.endswith(".xlsx") or filename.startswith("~$"):
            return
        # Small delay to ensure file is fully written before reading
        time.sleep(2)
        print(f"\n[Watcher] Detected: {filename}")
        try:
            hse_bot.main(path)
        except Exception as e:
            print(f"[Watcher] Error processing {filename}: {e}")


if __name__ == "__main__":
    os.makedirs(WATCH_DIR, exist_ok=True)
    print(f"[Watcher] Watching {WATCH_DIR} for new Excel files...")
    print("[Watcher] Drop a .xlsx file into input/ to trigger. Press Ctrl+C to stop.\n")

    handler = ExcelHandler()
    observer = Observer()
    observer.schedule(handler, WATCH_DIR, recursive=False)
    observer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
        print("\n[Watcher] Stopped.")
    observer.join()
