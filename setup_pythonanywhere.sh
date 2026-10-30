#!/bin/bash
set -e

echo "=================================================="
echo "🚀 MEMASANG FINANCE KEPIN DI PYTHONANYWHERE"
echo "=================================================="

cd ~
if [ -d "finance-kepin" ]; then
    echo "Updating existing finance-kepin repository..."
    cd finance-kepin
    git pull origin main
else
    echo "Cloning finance-kepin repository..."
    git clone https://github.com/EvanzaK/finance-kepin.git
    cd finance-kepin
fi

echo "📦 Menginstal pustaka Python yang dibutuhkan..."
pip install --user -r requirements.txt

echo "=================================================="
echo "✅ Instalasi paket Python selesai!"
echo "Langkah berikutnya: Buka tab 'Web' di PythonAnywhere."
echo "=================================================="
