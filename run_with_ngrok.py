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
        try:
            from pyngrok import ngrok
            from dotenv import load_dotenv
            
            load_dotenv()
            
            print(f"[INFO] Starting ngrok on port {port}...", flush=True)
            # Connect to ngrok
            public_url = ngrok.connect(port).public_url
            os.environ['EXTERNAL_URL'] = public_url
            # Print with green color highlight
            print(f"\033[92m[INFO] Ngrok public URL: {public_url}\033[0m", flush=True)
        except ImportError:
            print("[INFO] pyngrok not installed. Install it with 'pip install pyngrok' for public tunnel.", flush=True)
        except Exception as e:
            print(f"[WARNING] Error with ngrok: {e}", flush=True)
    
    # Start the app
    # Run without the Werkzeug reloader/debugger to avoid multiprocessing native crashes
    app.run(host='127.0.0.1', port=port, debug=False)

if __name__ == '__main__':
    run_dev()
