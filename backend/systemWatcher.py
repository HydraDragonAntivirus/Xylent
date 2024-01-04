import os
import win32file
import win32con
import threading
import queue
from queue import Queue
import psutil
import concurrent.futures
from parseJson import ParseJson

FILE_ACTION_ADDED = 0x00000001
FILE_ACTION_REMOVED = 0x00000002
FILE_ACTION_MODIFIED = 0x00000003

# Initialize ParseJson
XYLENT_NEW_PROCESS_INFO = ParseJson('./config', 'new_processes.json', {})

# Add global declarations for 'printed_processes' and 'previous_list'
printed_processes = set()
previous_list = set()
results_queue = Queue()  # Define results_queue as a global variable

def systemWatcher(XylentScanner, SYSTEM_DRIVE, thread_resume):
    XYLENT_SCAN_CACHE = ParseJson('./config', 'xylent_scancache', {})
    XYLENT_CACHE_MAXSIZE = 500000  # 500KB
    file_queue = Queue()

    def process_file_queue():
        while thread_resume.is_set():
            try:
                path_to_scan = file_queue.get(timeout=0.01)  # Timeout to avoid blocking indefinitely
                print(f"Processing file: {path_to_scan}")

                try:
                    if os.path.isfile(path_to_scan):
                        verdict = XylentScanner.scanFile(path_to_scan)
                        XYLENT_SCAN_CACHE.setVal(path_to_scan, verdict)
                        results_queue.put(verdict)  # Put the result in the queue
                        print(f"Scanned and cached: {path_to_scan}")
                except Exception as e:
                    print(e)
                    print(f"Error scanning {path_to_scan}")

            except queue.Empty:
                pass  # Queue is empty, continue checking

            if os.path.getsize(XYLENT_SCAN_CACHE.PATH) >= XYLENT_CACHE_MAXSIZE:
                XYLENT_SCAN_CACHE.purge()
                print("Purging")

    def file_monitor():
        while thread_resume.is_set():
            # File monitoring
            path_to_watch = SYSTEM_DRIVE + "\\"
            hDir = win32file.CreateFile(
                path_to_watch,
                1,
                win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE | win32con.FILE_SHARE_DELETE,
                None,
                win32con.OPEN_EXISTING,
                win32con.FILE_FLAG_BACKUP_SEMANTICS,
                None
            )

            results = win32file.ReadDirectoryChangesW(
                hDir,
                1024,
                True,
                win32con.FILE_NOTIFY_CHANGE_FILE_NAME |
                win32con.FILE_NOTIFY_CHANGE_DIR_NAME |
                win32con.FILE_NOTIFY_CHANGE_ATTRIBUTES |
                win32con.FILE_NOTIFY_CHANGE_SIZE |
                win32con.FILE_NOTIFY_CHANGE_LAST_WRITE |
                win32con.FILE_NOTIFY_CHANGE_SECURITY |
                FILE_ACTION_ADDED |
                FILE_ACTION_MODIFIED |
                FILE_ACTION_REMOVED,
                None,
                None
            )

            for action, file in results:
                path_to_scan = os.path.join(path_to_watch, file)
                print(path_to_scan)  # Print the path for debugging purposes
                result = XylentScanner.scanFile(path_to_scan)
                results_queue.put(result)  # Put the result in the queue

    def watch_processes():
        global printed_processes
        global previous_list

        # Print the initially running processes
        initial_processes = get_running_processes()
        print("Initially running processes:")
        print(initial_processes)

        printed_processes = set()

        # Load new processes using ParseJson
        new_processes = load_new_processes()

        # Initialize previous_list
        previous_list = initial_processes

        while thread_resume.is_set():
            try:
                # Get current running processes
                current_list = get_running_processes()

                # Compare with the previous list and find new processes
                newly_started_processes = current_list - previous_list
                new_processes.update(dict.fromkeys(newly_started_processes))

                if newly_started_processes:
                    with concurrent.futures.ThreadPoolExecutor() as executor:
                        # Submit each task individually and pass the required arguments
                        futures = [executor.submit(new_process_checker, info, XylentScanner, results_queue) for info in newly_started_processes]
                        concurrent.futures.wait(futures)

                    # Print new processes once
                    print("Newly started processes:")
                    print(newly_started_processes)

                    # Update printed_processes to avoid printing the same processes again
                    printed_processes.update(newly_started_processes)

                # Update the previous list
                previous_list = current_list

                # Save the updated new processes list to the file using ParseJson
                save_new_processes(list(new_processes))
            except Exception as e:
                print(f"Error in watch_processes: {e}")

    def load_new_processes():
        try:
            return XYLENT_NEW_PROCESS_INFO.parseDataFile([])
        except Exception:
            return []

    def save_new_processes(new_processes):
        XYLENT_NEW_PROCESS_INFO.setVal("new_processes", new_processes)

    def get_running_processes():
        processes = set()
        for p in psutil.process_iter(['exe', 'cmdline', 'ppid']):
            try:
                if p.info is not None and 'exe' in p.info:
                    exe = p.info['exe']
                    cmdline = tuple(p.info.get('cmdline', []))
                    ppid = p.info.get('ppid', None)
                    processes.add((exe, cmdline, ppid))
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, TypeError):
                pass  # Skip processes that are inaccessible or no longer exist
            except Exception as e:
                print(f"Error getting process info: {e}")
        return processes

    def new_process_checker(process_info, XylentScanner, results_queue):
        global printed_processes

        # process_info is a tuple (exe, cmdline, pid)
        exe, cmdline, pid = process_info

        if exe not in printed_processes:
            # Print the running file only once
            print(f"Running File: {exe}")
            printed_processes.add(exe)

            parent_process_info = get_parent_process_info(pid)
            if parent_process_info is None or parent_process_info.get('exe') is None:
                return  # Skip processing if parent process info is None or has no executable information

            parent_path = parent_process_info['exe']

            # Check if parent and child have the same location
            if parent_path != "Unknown" and exe.startswith(parent_path):
                return  # Skip processing if they have the same location

            # Check if parent and child have the same full path
            if os.path.abspath(exe) == os.path.abspath(parent_path):
                return  # Skip processing if they have the same full path

            message = f"Path: {exe}, Parent Process Path: {parent_path}, Command Line: {cmdline}"

            # Print to the console
            print("New Process Detected:", message)

            # Check if the command line includes paths
            if isinstance(cmdline, list):  # Ensure cmdline is a list
                paths = [arg for arg in cmdline if os.path.isabs(arg) and os.path.exists(arg)]
                if paths:
                    print(f"Command Line includes paths: {paths}, scanning related folder for process {exe}")
                    # Assuming you have a method named 'scanFile' in your Scanner class
                    for path in paths:
                        result = XylentScanner.scanFile(path)
                        results_queue.put(result)  # Put the result in the queue
        # Include the running file itself in the path_to_scan
        path_to_scan = exe
        result = XylentScanner.scanFile(path_to_scan)
        results_queue.put(result)  # Put the result in the queue

    def get_parent_process_info(file_path):
        try:
            process = psutil.Process(os.getpid())
            for parent in process.parents():
                if parent.exe() == file_path:
                    return {
                        'name': parent.name(),
                        'exe': parent.exe(),
                        'cmdline': parent.cmdline(),
                        'pid': parent.pid,
                    }
            return None
        except psutil.NoSuchProcess:
            print(f"Error: No such process with path {file_path}")
        except psutil.AccessDenied:
            print(f"Error: Access denied while retrieving information for path {file_path}")
        except Exception as e:
            print(f"An unexpected error occurred while getting parent process info for path {file_path}: {e}")

        return None

    monitor_thread = threading.Thread(target=file_monitor)
    monitor_thread.start()

    process_queue_thread = threading.Thread(target=process_file_queue)
    process_queue_thread.start()

    watch_processes_thread = threading.Thread(target=watch_processes)
    watch_processes_thread.start()

    monitor_thread.join()  # Wait for the file monitor to finish
    process_queue_thread.join()  # Wait for the file processing thread to finish
    watch_processes_thread.join()  # Wait for the process monitoring thread to finish

    print("RTP waiting to start...")
