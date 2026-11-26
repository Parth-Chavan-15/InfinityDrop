import os
import time
import random
import string
import socket
import threading
import shutil
from flask import Flask, request, render_template, make_response, jsonify, send_from_directory
from flask_cors import CORS
from werkzeug.utils import secure_filename

app = Flask(__name__)

# --- CONFIGURATION & FOLDERS ---
TEMP_FOLDER = 'temp_chunks'
UPLOAD_FOLDER = 'final_uploads'
app.config['MAX_CONTENT_LENGTH'] = None 

# CORS: ONLY client transfer endpoints are exposed to other devices
CORS(app, resources={
    r"/upload": {"origins": "*"},
    r"/files": {"origins": "*"},
    r"/download/*": {"origins": "*"},
    r"/reset-pin": {"origins": "*"}
})

# Startup Cleanup & Directory Setup
shutil.rmtree(TEMP_FOLDER, ignore_errors=True)
os.makedirs(TEMP_FOLDER, exist_ok=True)
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

assemble_lock = threading.Lock()

# --- SECURITY: HOST SECRET TOKEN (Prevents CSRF on Host endpoints) ---
HOST_TOKEN = ''.join(random.choices(string.ascii_letters + string.digits, k=32))

# --- BRUTE-FORCE RATE LIMITER FOR PIN AUTHENTICATION ---
FAILED_ATTEMPTS = {}
RATE_LIMIT_LOCK = threading.Lock()

def is_rate_limited(ip):
    now = time.time()
    with RATE_LIMIT_LOCK:
        attempts = FAILED_ATTEMPTS.get(ip, [])
        attempts = [t for t in attempts if now - t < 60]
        FAILED_ATTEMPTS[ip] = attempts
        return len(attempts) >= 5

def record_failed_attempt(ip):
    now = time.time()
    with RATE_LIMIT_LOCK:
        attempts = FAILED_ATTEMPTS.get(ip, [])
        attempts = [t for t in attempts if now - t < 60]
        attempts.append(now)
        FAILED_ATTEMPTS[ip] = attempts

def clear_failed_attempts(ip):
    with RATE_LIMIT_LOCK:
        FAILED_ATTEMPTS.pop(ip, None)

# --- NETWORK & SERVER IP HELPER ---
def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('10.254.254.254', 1))
        ip = s.getsockname()[0]
    except Exception:
        ip = '127.0.0.1'
    finally:
        s.close()
    return ip

SERVER_IP = get_local_ip()

def is_local_request():
    """Detect if request originates from the host machine"""
    remote = request.remote_addr
    if remote in ('127.0.0.1', '::1', 'localhost', SERVER_IP):
        return True
    try:
        host_ips = socket.gethostbyname_ex(socket.gethostname())[2]
        if remote in host_ips:
            return True
    except Exception:
        pass
    return False

def check_host_auth():
    """Strict authentication for Host Control APIs (Local Origin + Secret Token)"""
    if not is_local_request():
        return False, "Forbidden: Host only"
    token = request.headers.get('X-Host-Token')
    if not token or token != HOST_TOKEN:
        return False, "Unauthorized: Invalid Host Token"
    return True, "OK"

# --- PIN & SESSION VARIABLES ---
def generate_pin():
    return ''.join(random.choices(string.digits, k=6))

SECRET_PIN = generate_pin()
AUTHORIZED_IP = None 

# --- PATH TRAVERSAL DEFENSE ---
def is_safe_path(base_dir, path):
    try:
        base = os.path.abspath(base_dir)
        target = os.path.abspath(path)
        return os.path.commonpath([base, target]) == base
    except Exception:
        return False

# --- HELPER: FILE SIZE FORMATTING ---
def format_size(bytes_size):
    for unit in ['B', 'KB', 'MB', 'GB']:
        if bytes_size < 1024.0:
            return f"{bytes_size:.1f} {unit}" if unit != 'B' else f"{bytes_size} B"
        bytes_size /= 1024.0
    return f"{bytes_size:.1f} TB"

def get_shared_files_list():
    files = []
    try:
        for f in os.listdir(UPLOAD_FOLDER):
            if f.startswith('.'):
                continue
            path = os.path.join(UPLOAD_FOLDER, f)
            if os.path.isfile(path) and is_safe_path(UPLOAD_FOLDER, path):
                size = os.path.getsize(path)
                files.append({
                    "name": f,
                    "size": format_size(size),
                    "bytes": size
                })
    except Exception:
        pass
    return files

# --- SECURITY HELPER FOR CLIENT REQUESTS ---
def check_auth():
    """Returns (True, 'OK') if request is authorized, else (False, error_message)"""
    global AUTHORIZED_IP, SECRET_PIN

    client_ip = request.remote_addr

    # 1. Brute-Force Rate Limiting Check
    if is_rate_limited(client_ip):
        print(f"🛑 [Rate Limited] Blocked brute force attempt from {client_ip}")
        return False, "Too many failed attempts. Please wait 60 seconds."

    # 2. PIN Check FIRST! (Prevents unauthorized probes from locking the session IP)
    pin = request.headers.get('X-Upload-PIN') or request.args.get('token')
    if not pin or pin.strip() != SECRET_PIN:
        record_failed_attempt(client_ip)
        print(f"⚠️ [Auth Denied] Invalid or missing PIN from {client_ip}")
        return False, "Unauthorized: Wrong PIN"

    # Reset failed attempts upon successful PIN authentication
    clear_failed_attempts(client_ip)

    # 3. IP Lock Check (Only active after PIN is verified)
    if AUTHORIZED_IP is None:
        AUTHORIZED_IP = client_ip
        print(f"🔒 [Device Connected] Session locked to IP: {AUTHORIZED_IP}")
    elif client_ip != AUTHORIZED_IP:
        print(f"⚠️ [Device Busy] {client_ip} blocked: active session on {AUTHORIZED_IP}")
        return False, f"Busy: Another device ({AUTHORIZED_IP}) is currently connected."

    return True, "OK"

# --- MAIN ROUTE ---
@app.route('/')
def index():
    if is_local_request() and request.args.get('mode') != 'client':
        return render_template(
            'host.html',
            server_ip=SERVER_IP,
            port=5000,
            pin=SECRET_PIN,
            authorized_ip=AUTHORIZED_IP,
            upload_folder=os.path.abspath(UPLOAD_FOLDER),
            host_token=HOST_TOKEN
        )
    return render_template('index.html')

# --- SECURE FILE LISTING (FOR CLIENTS) ---
@app.route('/files', methods=['GET'])
def list_files():
    is_valid, msg = check_auth()
    if not is_valid:
        status_code = 429 if "Too many" in msg else 403
        return make_response(msg, status_code)
    return jsonify(get_shared_files_list())

# --- SECURE DOWNLOAD ---
@app.route('/download/<path:filename>', methods=['GET'])
def download_file(filename):
    is_valid, msg = check_auth()
    if not is_valid:
        status_code = 429 if "Too many" in msg else 403
        return make_response(msg, status_code)

    safe_name = secure_filename(filename)
    target_path = os.path.join(UPLOAD_FOLDER, safe_name)
    if not is_safe_path(UPLOAD_FOLDER, target_path):
        return make_response("Forbidden: Path traversal detected", 403)

    return send_from_directory(UPLOAD_FOLDER, safe_name, as_attachment=True)

# --- CHUNKED RESUMABLE UPLOAD ---
@app.route('/upload', methods=['GET', 'POST'])
def upload():
    global AUTHORIZED_IP, SECRET_PIN

    is_valid, msg = check_auth()
    if not is_valid:
        status_code = 429 if "Too many" in msg else 403
        return make_response(msg, status_code)

    identifier = request.args.get('resumableIdentifier')
    filename = request.args.get('resumableFilename')
    try:
        chunk_number = int(request.args.get('resumableChunkNumber'))
        total_chunks = int(request.args.get('resumableTotalChunks'))
        total_size = int(request.args.get('resumableTotalSize'))
    except (TypeError, ValueError):
        return make_response("Invalid Chunk Metadata", 400)

    if not identifier or not filename:
        return make_response("Invalid Request", 400)

    # Sanitize identifier and filename
    safe_id = secure_filename(identifier)
    safe_name = secure_filename(filename)
    if not safe_name:
        safe_name = f"upload_{random.randint(1000, 9999)}"

    session_identifier = f"{request.remote_addr}_{safe_id}"

    # Disk Space Protection
    if chunk_number == 1:
        total, used, free = shutil.disk_usage(TEMP_FOLDER)
        if total_size > (free - 500*1024*1024):
            return make_response("Error: Not enough disk space", 507)

    chunk_filename = f"{session_identifier}_part_{chunk_number}"
    chunk_path = os.path.join(TEMP_FOLDER, chunk_filename)
    if not is_safe_path(TEMP_FOLDER, chunk_path):
        return make_response("Forbidden", 403)

    if request.method == 'GET':
        if os.path.exists(chunk_path): 
            return make_response("Chunk exists", 200)
        return make_response("Chunk not found", 404)

    if request.method == 'POST':
        try:
            file = request.files['file']
            file.save(chunk_path)
        except OSError:
            cleanup_failed_upload(session_identifier)
            return make_response("Disk Full", 507)

        if is_file_complete(session_identifier, total_chunks):
            with assemble_lock:
                if is_file_complete(session_identifier, total_chunks):
                    reassemble_file(session_identifier, safe_name, total_chunks)
                    return make_response("File Uploaded", 200)

        return make_response("Chunk uploaded", 200)

# Helpers for chunked upload
def is_file_complete(identifier, total_chunks):
    for i in range(1, total_chunks + 1):
        if not os.path.exists(os.path.join(TEMP_FOLDER, f"{identifier}_part_{i}")):
            return False
    return True

def cleanup_failed_upload(identifier):
    for fname in os.listdir(TEMP_FOLDER):
        if fname.startswith(identifier):
            try: 
                os.remove(os.path.join(TEMP_FOLDER, fname))
            except: 
                pass

def reassemble_file(identifier, safe_name, total_chunks):
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
            try:
                os.remove(chunk_path)
            except:
                pass
    print(f"✅ Success! File received and saved as: {os.path.basename(final_path)}")

# --- BATCH RESET ENDPOINT (FOR CLIENTS) ---
@app.route('/reset-pin', methods=['POST'])
def reset_pin():
    global SECRET_PIN, AUTHORIZED_IP
    
    is_valid, msg = check_auth()
    if not is_valid: 
        status_code = 429 if "Too many" in msg else 403
        return make_response(msg, status_code)

    SECRET_PIN = generate_pin()
    AUTHORIZED_IP = None
    print(f"\n🔒 Batch complete. Session unlocked. New PIN: {SECRET_PIN}")
    return jsonify({"status": "success", "pin": SECRET_PIN})

# --- HOST API ENDPOINTS (STRICTLY SECURED BY HOST TOKEN & LOCAL ORIGIN) ---
@app.route('/api/host/status', methods=['GET'])
def host_status():
    is_valid, msg = check_host_auth()
    if not is_valid:
        return make_response(msg, 403)
    return jsonify({
        "server_ip": SERVER_IP,
        "port": 5000,
        "pin": SECRET_PIN,
        "authorized_ip": AUTHORIZED_IP,
        "upload_folder": os.path.abspath(UPLOAD_FOLDER),
        "files": get_shared_files_list()
    })

@app.route('/api/host/upload', methods=['POST'])
def host_upload():
    is_valid, msg = check_host_auth()
    if not is_valid:
        return make_response(msg, 403)
    if 'files' not in request.files:
        return jsonify({"error": "No files uploaded"}), 400
    
    uploaded_files = request.files.getlist('files')
    saved = []
    for f in uploaded_files:
        if f.filename:
            safe_name = secure_filename(f.filename)
            if not safe_name:
                safe_name = f"file_{random.randint(1000, 9999)}"
            target_path = os.path.join(UPLOAD_FOLDER, safe_name)
            if not is_safe_path(UPLOAD_FOLDER, target_path):
                continue
            base, ext = os.path.splitext(safe_name)
            c = 1
            while os.path.exists(target_path):
                target_path = os.path.join(UPLOAD_FOLDER, f"{base}_{c}{ext}")
                c += 1
            f.save(target_path)
            saved.append(os.path.basename(target_path))
    print(f"📁 Host added {len(saved)} file(s) to final_uploads: {', '.join(saved)}")
    return jsonify({"status": "success", "saved": saved})

@app.route('/api/host/delete/<path:filename>', methods=['POST', 'DELETE'])
def host_delete(filename):
    is_valid, msg = check_host_auth()
    if not is_valid:
        return make_response(msg, 403)
    safe_name = secure_filename(filename)
    target_path = os.path.join(UPLOAD_FOLDER, safe_name)
    if not is_safe_path(UPLOAD_FOLDER, target_path):
        return make_response("Forbidden", 403)

    if os.path.exists(target_path):
        import time, gc
        gc.collect()
        for attempt in range(3):
            try:
                os.remove(target_path)
                print(f"🗑️ Host deleted: {safe_name}")
                return jsonify({"status": "success"})
            except PermissionError:
                time.sleep(0.15)
                gc.collect()
        try:
            os.remove(target_path)
            return jsonify({"status": "success"})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    return jsonify({"error": "File not found"}), 404

@app.route('/api/host/reset-session', methods=['POST'])
def host_reset_session():
    global SECRET_PIN, AUTHORIZED_IP
    is_valid, msg = check_host_auth()
    if not is_valid:
        return make_response(msg, 403)
    SECRET_PIN = generate_pin()
    AUTHORIZED_IP = None
    print(f"\n🔄 Session reset from Host Dashboard. New PIN: {SECRET_PIN}")
    return jsonify({"status": "success", "pin": SECRET_PIN})

@app.route('/api/host/open-folder', methods=['POST'])
def host_open_folder():
    is_valid, msg = check_host_auth()
    if not is_valid:
        return make_response(msg, 403)
    try:
        os.startfile(os.path.abspath(UPLOAD_FOLDER))
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    print(r"""
=========================================================
  ∞ INFINITY DROP SECURE - LOCAL TRANSFER HUB
=========================================================
  🖥️ Host Dashboard : http://localhost:5000
                     (Open on this PC to manage files & view QR code)
  📱 Mobile Connect  : http://""" + SERVER_IP + r""":5000
                     (Open on phone or scan QR code on dashboard)
  🔒 6-Digit PIN     : """ + SECRET_PIN + r"""
  📂 Local Folder    : """ + os.path.abspath(UPLOAD_FOLDER) + r"""
=========================================================
""")
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)
