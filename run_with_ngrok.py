import os
import sys
import faulthandler
import subprocess
import time
import json
import urllib.request
import re
from app import create_app

# Enable faulthandler early to capture native crashes and Python tracebacks
faulthandler.enable(all_threads=True)

def run_dev():
    # Set the Flask environment
    os.environ['FLASK_ENV'] = 'development'
    os.environ['EMS_SINGLE_PROCESS'] = '1'
    
    port = 5000

    # Ensure the port is free before starting (only on the first run, not in the reloader)
    if os.environ.get('WERKZEUG_RUN_MAIN') != 'true':
        import subprocess
        try:
            if os.name == 'nt':
                # Windows: Find and kill process on the port
                # Using netstat to find the PID of the process listening on the port
                result = subprocess.run(['netstat', '-ano'], capture_output=True, text=True)
                for line in result.stdout.splitlines():
                    if f':{port}' in line and 'LISTENING' in line:
                        parts = line.strip().split()
                        if len(parts) >= 5:
                            pid = parts[-1]
                            # Kill the process
                            subprocess.run(['taskkill', '/F', '/PID', pid], capture_output=True)
                            print(f"\033[93m[CLEANUP] Killed process {pid} listening on port {port}\033[0m")
            else:
                # Linux/macOS: Use fuser and pkill
                subprocess.run(['fuser', '-k', f'{port}/tcp'], capture_output=True)
                subprocess.run(['pkill', 'ngrok'], capture_output=True)
                print(f"[CLEANUP] Cleaning up port {port} and existing ngrok processes...")
        except Exception as e:
            # Silent fail if cleanup fails (e.g. no process found)
            pass

    # Initialize the Flask app
    app = create_app('development')
    
    # Try to use ngrok for public URL testing if installed
    # ONLY start ngrok in the main process, not the reloader child
    if os.environ.get('WERKZEUG_RUN_MAIN') != 'true':
        ngrok_bin = None
        
        # Find ngrok binary (prefer system paths)
        potential_paths = [
            "/home/ishan-acharya/.local/bin/ngrok",
            "/usr/local/bin/ngrok",
            "/usr/bin/ngrok",
        ]
        
        for path in potential_paths:
            if os.path.exists(path) and os.access(path, os.X_OK):
                ngrok_bin = path
                print(f"[INFO] Found ngrok at: {ngrok_bin}", flush=True)
                break
        
        if ngrok_bin:
            try:
                from dotenv import load_dotenv
                load_dotenv()
                
                # Build ngrok command
                ngrok_cmd = [ngrok_bin, 'http', str(port)]
                
                print(f"[INFO] Starting ngrok on port {port}...", flush=True)
                # Start ngrok in shell background without waiting
                import subprocess
                log_path = "/tmp/ngrok.log"
                log_file = open(log_path, "w", encoding="utf-8")
                subprocess.Popen(
                    ngrok_cmd,
                    stdout=log_file,
                    stderr=log_file,
                    start_new_session=True
                )

                def wait_for_ngrok_url():
                    log_pattern = re.compile(r"https://[\w\-\.]+ngrok(?:-free)?\.[a-z]+")
                    last_size = 0
                    for attempt in range(90):
                        try:
                            if os.path.exists(log_path):
                                with open(log_path, "r", encoding="utf-8", errors="ignore") as handle:
                                    handle.seek(last_size)
                                    chunk = handle.read()
                                    last_size = handle.tell()
                                match = log_pattern.search(chunk)
                                if match:
                                    public_url = match.group(0)
                                    os.environ['EXTERNAL_URL'] = public_url
                                    print(f"[INFO] Ngrok public URL: {public_url}", flush=True)
                                    return public_url

                            with urllib.request.urlopen('http://127.0.0.1:4040/api/tunnels', timeout=1) as resp:
                                data = json.load(resp)
                            tunnels = data.get('tunnels', [])
                            if tunnels:
                                public_url = tunnels[0].get('public_url')
                                if public_url:
                                    os.environ['EXTERNAL_URL'] = public_url
                                    print(f"[INFO] Ngrok public URL: {public_url}", flush=True)
                                    return public_url
                        except Exception:
                            pass

                        if attempt % 10 == 0:
                            print("[INFO] Waiting for ngrok public URL...", flush=True)
                        time.sleep(0.5)

                    print("[INFO] Ngrok tunnel started, but the public URL was not available yet. Check http://127.0.0.1:4040", flush=True)
                    return None

                wait_for_ngrok_url()
                
            except Exception as e:
                print(f"[WARNING] Error with ngrok: {e}", flush=True)
        else:
            print("[INFO] ngrok binary not found. Running without public tunnel.", flush=True)
    
    # Start the app
    # Run without the Werkzeug reloader/debugger to avoid multiprocessing native crashes
    app.run(host='127.0.0.1', port=port, debug=False)

if __name__ == '__main__':
    run_dev()
