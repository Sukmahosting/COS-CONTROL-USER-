# COS-CONTROL-USER-
# Instalasi In termux
# Bash:
`Update & upgrade paket
pkg update && pkg upgrade -y
pkg install python python-pip git wget curl -y
pkg install libjpeg-turbo libxml2 libxslt openssl -y`

# Instalasi Modul
`# Upgrade pip dulu
pip install --upgrade pip
pip install flask flask-socketio qrcode Pillow cryptography requests
pip install psutil speedtest-cli`

# Set-Up Sctipt
Clone repository (gunakan versi khusus Termux)
git clone https://github.com/example/termux-monitoring-tool.git
cd termux-monitoring-tool`

# Buat struktur folder
mkdir -p logs client_data exports
# Buat config khusus Termux
cat > config_termux.json << EOF
{
  "platform": "android_termux",
  "storage_path": "/data/data/com.termux/files/home/storage/shared",
  "allowed_folders": [
    "Download",
    "Documents",
    "Pictures"
  ],
  "permissions": {
    "accessibility": false,
    "root": false,
    "storage": true
  }
}
EOF

# Donate
_Saweria.co: https://saweria.co/GDXPIXEL_
