#!/bin/bash
cd ~/vps_x_bot
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
nohup python vps_scheduler.py --fecha "2026-07-20 08:00" --texto "In 1587, 115 English settlers vanished from Roanoke Island without a trace. Their homes were dismantled, and no bodies were ever found. The only clue left behind? The word 'CROATOAN' carved into a wooden post 🌫️🌳. #History #Mystery #Roanoke" --imagen "roanoke_image.png" > scheduler.log 2>&1 &
echo "Despliegue exitoso. El script esta corriendo en background."
