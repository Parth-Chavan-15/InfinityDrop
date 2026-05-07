import os
import random
import string
import socket
import threading
import shutil
from flask import Flask, request, render_template, make_response, jsonify, send_from_directory
from flask_cors import CORS
from werkzeug.utils import secure_filename

app = Flask(__name__)

# --- CONFIGURATION ---
TEMP_FOLDER = 'temp_chunks'
UPLOAD_FOLDER = 'final_uploads'
app.config['MAX_CONTENT_LENGTH'] = None 
CORS(app, resources={r"/*": {"origins": "*"}}) 

# Startup Cleanup
shutil.rmtree(TEMP_FOLDER, ignore_errors=True)
os.makedirs(TEMP_FOLDER, exist_ok=True)
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

assemble_lock = threading.Lock()

# GLOBAL VARIABLES
SECRET_PIN = ""
AUTHORIZED_IP = None 

def generate_pin():
    return ''.join(random.choices(string.digits, k=6))

SECRET_PIN = generate_pin()

# --- SECURITY HELPER ---
def check_auth():
    """Returns True if request is authorized, else False"""
    global AUTHORIZED_IP
    
    # 1. IP Lock Check
    if AUTHORIZED_IP is None:
        AUTHORIZED_IP = request.remote_addr
    if request.remote_addr != AUTHORIZED_IP:
        return False, "Busy: Another device is connected."

    # 2. PIN Check
    # Check Header (preferred) or Query Param (for downloads)
    pin = request.headers.get('X-Upload-PIN') or request.args.get('token')
    if pin != SECRET_PIN:
        return False, "Unauthorized: Wrong PIN"
        
    return True, "OK"

@app.route('/')
def index():
    return render_template('index.html')

# --- SECURE FILE LISTING ---
@app.route('/files', methods=['GET'])
def list_files():
    is_valid, msg = check_auth()
    if not is_valid:
        return make_response(msg, 403)

    try:
        files = os.listdir(UPLOAD_FOLDER)
        # Filter hidden files
        files = [f for f in files if not f.startswith('.')]
        return jsonify(files)
    except:
        return jsonify([])

# --- SECURE DOWNLOAD ---
@app.route('/download/<path:filename>', methods=['GET'])
def download_file(filename):
    # For downloads, browsers send GET requests where headers are hard to customize.
    # We will accept the PIN via URL query parameter ?token=123456
    is_valid, msg = check_auth()
    if not is_valid:
        return make_response(msg, 403)
        
    return send_from_directory(UPLOAD_FOLDER, filename, as_attachment=True)

@app.route('/upload', methods=['GET', 'POST'])
def upload():
    global AUTHORIZED_IP, SECRET_PIN

    # Auth Check
    is_valid, msg = check_auth()
    if not is_valid:
        return make_response(msg, 403)

    identifier = request.args.get('resumableIdentifier')
    filename = request.args.get('resumableFilename')
    chunk_number = int(request.args.get('resumableChunkNumber'))
    total_chunks = int(request.args.get('resumableTotalChunks'))
    total_size = int(request.args.get('resumableTotalSize'))

    if not identifier or not filename:
        return make_response("Invalid Request", 500)

    identifier = f"{request.remote_addr}_{identifier}"

    if chunk_number == 1:
        total, used, free = shutil.disk_usage(TEMP_FOLDER)
        if total_size > (free - 500*1024*1024):
            return make_response("Error: Not enough disk space", 507)

    chunk_filename = f"{identifier}_part_{chunk_number}"
    chunk_path = os.path.join(TEMP_FOLDER, chunk_filename)

    if request.method == 'GET':
        if os.path.exists(chunk_path): return make_response("Chunk exists", 200)
        return make_response("Chunk not found", 404)

    if request.method == 'POST':
        try:
            file = request.files['file']
            file.save(chunk_path)
        except OSError:
            cleanup_failed_upload(identifier)
            return make_response("Disk Full", 507)

        if is_file_complete(identifier, total_chunks):
            with assemble_lock:
                if is_file_complete(identifier, total_chunks):
                    reassemble_file(identifier, filename, total_chunks)
                    
                    # --- NOTE: PIN ROTATION IS DISABLED HERE ---
                    # This allows the batch to finish. 
                    # The Frontend calls /reset-pin when done.
                    return make_response("File Uploaded", 200)

        return make_response("Chunk uploaded", 200)

# Helpers
def is_file_complete(identifier, total_chunks):
    for i in range(1, total_chunks + 1):
        if not os.path.exists(os.path.join(TEMP_FOLDER, f"{identifier}_part_{i}")):
            return False
    return True

def cleanup_failed_upload(identifier):
    for fname in os.listdir(TEMP_FOLDER):
        if fname.startswith(identifier):
            try: os.remove(os.path.join(TEMP_FOLDER, fname))
            except: pass

def reassemble_file(identifier, filename, total_chunks):
    safe_name = secure_filename(filename)
    final_path = os.path.join(UPLOAD_FOLDER, safe_name)
    base, ext = os.path.splitext(safe_name)
    counter = 1
    while os.path.exists(final_path):
        final_path = os.path.join(UPLOAD_FOLDER, f"{base}_{counter}{ext}")
        counter += 1
    
    with open(final_path, 'wb') as final_file:
        for i in range(1, total_chunks + 1):
            chunk_name = f"{identifier}_part_{i}"
            chunk_path = os.path.join(TEMP_FOLDER, chunk_name)
            with open(chunk_path, 'rb') as chunk_file:
                final_file.write(chunk_file.read())
            os.remove(chunk_path)
    print(f"✅ Success! Saved as: {os.path.basename(final_path)}")

# --- [ADDED SECTION] NEW ENDPOINT FOR BATCH RESET ---
@app.route('/reset-pin', methods=['POST'])
def reset_pin():
    global SECRET_PIN, AUTHORIZED_IP
    
    # 1. Verify the current user is allowed to reset
    is_valid, msg = check_auth()
    if not is_valid: return make_response(msg, 403)

    # 2. Rotate the PIN now that the batch is done
    SECRET_PIN = generate_pin()
    AUTHORIZED_IP = None
    print()
    print(f"🔒 Batch Complete. PIN Rotated to: {SECRET_PIN}")
    return jsonify({"status": "success"})
# ----------------------------------------------------

if __name__ == '__main__':
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('10.254.254.254', 1))
        IP = s.getsockname()[0]
    except: IP = '127.0.0.1'
    finally: s.close()
    
    print(f"\n🚀 INFINITY DROP SECURE IS LIVE")
    print(f"📡 Connect: http://{IP}:5000")
    print(f"🔒 PIN: {SECRET_PIN}")
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)