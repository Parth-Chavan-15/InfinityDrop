# ∞ InfinityDrop

**Secure, high-speed, peer-to-peer local file transfer using Python and Flask.**

InfinityDrop is a web-based application that allows seamless two-way file sharing between devices on the same Wi-Fi network. It completely bypasses the internet, ensuring maximum transfer speeds, zero data consumption, and complete privacy.

## ✨ Features

* **Blazing Fast Local Transfers:** Uses your local router's bandwidth, making it 10x-20x faster than Bluetooth.
* **Chunked Upload Protocol:** Large files are split into 1MB chunks. If a network hiccup occurs, it resumes exactly where it left off without starting over.
* **Batch Transfer Mode:** Select multiple files and upload them seamlessly in a single queue.
* **Dynamic PIN Authentication:** Generates a secure 6-digit session PIN. The PIN automatically rotates the moment a batch transfer completes, preventing unauthorized access.
* **Device Lock:** Once a device connects using the PIN, the session locks to that specific IP address, preventing "Man in the Middle" interceptions.
* **Cross-Platform:** No app installation required on the client device—just a modern web browser.

## 🚀 How to Run Locally

### Prerequisites
Make sure you have [Python](https://www.python.org/downloads/) installed on your system.

### 1. Clone the repository
```bash
git clone https://github.com/Parth-Chavan-15/InfinityDrop
cd InfinityDrop
```

### 2. Install Dependencies
Install the required Python packages using pip:
```bash
pip install -r requirements.txt
```

### 3. Start the Server
Run the Flask application:
```bash
python app.py
```

### 4. Connect
The terminal will output a local IP address (e.g., http://192.168.1.5:5000) and a 6-digit PIN.

Open that URL on any device connected to the same Wi-Fi network.

Enter the PIN to unlock the interface and start dropping files!

## 🛠️ Tech Stack
Backend: Python, Flask, Werkzeug

Frontend: HTML5, Vanilla JavaScript, CSS3

Libraries: Resumable.js (for chunked file handling), Flask-CORS

## 📁 Project Structure
<pre>
InfinityDrop/
├── app.py                # Main Flask server and API endpoints
├── requirements.txt      # Python dependencies
├── .gitignore            # Ignored files and folders
└── templates/
    └── index.html        # Frontend UI and client-side logic
</pre>