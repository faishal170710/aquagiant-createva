
import json
import threading
from datetime import datetime

import numpy as np
import paho.mqtt.client as mqtt

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score

# Made by CREATEVA

BROKER = "broker.hivemq.com"
PORT = 1883

TOPIC_DATA = "aquagiant/team01/pond01/data"
TOPIC_COMMAND = "aquagiant/team01/pond01/command"
TOPIC_STATUS = "aquagiant/team01/pond01/status"

app = FastAPI(title="AquaGiant AIoT")

# Shared data

lock = threading.Lock()

state = {
    "temperature": None,
    "ph": None,
    "do": None,
    "risk": None,
    "probability": None,
    "relay": "UNKNOWN",
    "recommendation": "Waiting for sensor",
    "updated_at": None,
    "history": []
}

# 1. SYNTHETIC DATASET AND MODEL TRAINING

np.random.seed(42)

N = 5000

temperature = np.random.uniform(15, 40, N)
ph = np.random.uniform(4, 10, N)
do = np.random.uniform(0, 12, N)

# hanya untuk tujuan demo, bukan data nyata
risk = (
    (do < 4.0) |
    (ph < 6.0) |
    (ph > 9.0) |
    (temperature > 34.0) |
    (temperature < 20.0)
).astype(int)

X = np.column_stack([
    temperature,
    ph,
    do
])

X_train, X_test, y_train, y_test = train_test_split(
    X,
    risk,
    test_size=0.2,
    random_state=42,
    stratify=risk
)

model = RandomForestClassifier(
    n_estimators=150,
    max_depth=8,
    random_state=42,
    class_weight="balanced"
)

model.fit(X_train, y_train)

accuracy = accuracy_score(
    y_test,
    model.predict(X_test)
)

print("AQUAGIANT AI INITIALIZED")
print("Synthetic test accuracy:", round(accuracy, 4))

# klient MQTT untuk komunikasi dengan sensor dan aktuator

mqtt_client = mqtt.Client(
    mqtt.CallbackAPIVersion.VERSION2,
    client_id="AquaGiant-Backend-Team01"
)

# Mengirim perintah ke aktuator melalui MQTT

def send_command(command):
    result = mqtt_client.publish(
        TOPIC_COMMAND,
        command,
        qos=0
    )

    if result.rc == mqtt.MQTT_ERR_SUCCESS:
        print("COMMAND SENT:", command)
    else:
        print("COMMAND FAILED:", command)

# proses data sensor dan menghasilkan rekomendasi

def process_sensor(data):

    temperature = float(data["temperature"])
    ph = float(data["ph"])
    do = float(data["do"])

    features = np.array([[
        temperature,
        ph,
        do
    ]])

    prediction = int(model.predict(features)[0])

    probability = float(
        model.predict_proba(features)[0][1]
    )

    # Menghasilkan rekomendasi berdasarkan aturan dan prediksi AI

    # Rule-based control:
    # Aerator is controlled by DO only.
    if do < 4.0:
        command = "ON"
        recommendation = "DO is low. Aerator activated."

    elif do <= 5.0:
        command = None
        recommendation = "DO is borderline. Maintain current relay state."

    else:
        command = "OFF"
        recommendation = "DO is sufficient for this demo threshold."

    # Machine Learning risk classification
    if prediction == 1:
        risk_label = "HIGH"
    else:
        risk_label = "NORMAL"

    # kondisi lingkungan yang tidak ideal dapat memicu peringatan tambahan, meskipun bukan perintah aerator langsung.

    alerts = []

    if ph < 6.0 or ph > 9.0:
        alerts.append("pH outside demo range")

    if temperature < 20.0 or temperature > 34.0:
        alerts.append("Temperature outside demo range")

    if alerts:
        recommendation += " Check: " + ", ".join(alerts)

    return {
        "temperature": temperature,
        "ph": ph,
        "do": do,
        "risk": risk_label,
        "probability": round(probability, 4),
        "command": command,
        "recommendation": recommendation
    }

# callback MQTT untuk koneksi dan pesan

def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        print("MQTT CONNECTED")
        client.subscribe(TOPIC_DATA)
        client.subscribe(TOPIC_STATUS)
    else:
        print("MQTT CONNECTION FAILED:", reason_code)


def on_message(client, userdata, message):

    try:
        payload = message.payload.decode()

        # feedback status dari aktuator
        if message.topic == TOPIC_STATUS:
            with lock:
                state["relay"] = payload
            return

        # data sensor
        if message.topic == TOPIC_DATA:

            sensor = json.loads(payload)

            result = process_sensor(sensor)

            with lock:

                state["temperature"] = result["temperature"]
                state["ph"] = result["ph"]
                state["do"] = result["do"]
                state["risk"] = result["risk"]
                state["probability"] = result["probability"]
                state["recommendation"] = result["recommendation"]
                state["updated_at"] = datetime.now().isoformat()

                record = {
                    "time": datetime.now().strftime("%H:%M:%S"),
                    "temperature": result["temperature"],
                    "ph": result["ph"],
                    "do": result["do"],
                    "risk": result["risk"]
                }

                state["history"].append(record)
                state["history"] = state["history"][-60:]

            # mengirim perintah ke aktuator jika diperlukan
            if result["command"] is not None:
                send_command(result["command"])

            print("AI RESULT:", result)

    except Exception as error:
        print("PROCESSING ERROR:", error)


mqtt_client.on_connect = on_connect
mqtt_client.on_message = on_message

# menyambungkan ke broker MQTT di thread terpisah agar tidak mengganggu FastAPI

def start_mqtt():

    try:
        mqtt_client.connect(BROKER, PORT, 60)
        mqtt_client.loop_start()

    except Exception as error:
        print("MQTT ERROR:", error)


threading.Thread(
    target=start_mqtt,
    daemon=True
).start()

# API ENDPOINTS

@app.get("/api/status")
def get_status():

    with lock:
        return dict(state)


@app.post("/api/manual/{command}")
def manual_control(command: str):

    command = command.upper()

    if command not in ["ON", "OFF"]:
        return {"success": False, "message": "Invalid command"}

    with lock:
        current_do = state["do"]

    if command == "OFF" and current_do is not None and current_do <= 5.0:
        return {
            "success": False,
            "message": "OFF rejected: DO is still low or borderline"
        }

    send_command(command)

    return {
        "success": True,
        "command": command
    }


@app.get("/api/model")
def model_info():

    return {
        "model": "Random Forest Classifier",
        "dataset": "Synthetic demonstration data",
        "test_accuracy": round(float(accuracy), 4),
        "warning": "Not validated with real pond data"
    }

# Dashboard HTML page

@app.get("/", response_class=HTMLResponse)
def dashboard():

    return """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">

<title>AquaGiant Dashboard</title>

<style>

* {
    box-sizing: border-box;
    margin: 0;
    padding: 0;
}

body {
    font-family: Arial, sans-serif;
    background: #07111c;
    color: #f1f5f9;
    padding: 25px;
}

header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 30px;
    flex-wrap: wrap;
    gap: 15px;
}

h1 {
    font-size: 25px;
}

.subtitle {
    color: #94a3b8;
    margin-top: 7px;
    font-size: 13px;
}

.badge {
    padding: 8px 13px;
    border-radius: 20px;
    background: #123c30;
    color: #4ade80;
    font-size: 12px;
}

.grid {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 15px;
}

.card {
    background: #111f2e;
    border: 1px solid #26384a;
    border-radius: 13px;
    padding: 20px;
    margin-bottom: 18px;
}

.card h3 {
    font-size: 13px;
    color: #94a3b8;
    font-weight: 500;
}

.value {
    font-size: 30px;
    font-weight: bold;
    margin-top: 15px;
}

.unit {
    color: #94a3b8;
    font-size: 13px;
}

.status {
    display: inline-block;
    margin-top: 13px;
    padding: 6px 10px;
    background: #26384a;
    border-radius: 6px;
    font-size: 12px;
}

.section {
    margin-top: 20px;
}

.section h2 {
    font-size: 17px;
    margin-bottom: 15px;
}

.control {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 20px;
    flex-wrap: wrap;
}

button {
    border: 0;
    padding: 11px 20px;
    border-radius: 7px;
    cursor: pointer;
    font-weight: bold;
    margin: 4px;
}

.on {
    background: #16a34a;
    color: white;
}

.off {
    background: #dc2626;
    color: white;
}

#risk {
    font-size: 23px;
    font-weight: bold;
    margin-top: 10px;
}

#recommendation {
    color: #cbd5e1;
    line-height: 1.6;
    margin-top: 12px;
}

table {
    width: 100%;
    border-collapse: collapse;
    font-size: 13px;
}

th, td {
    padding: 12px;
    border-bottom: 1px solid #26384a;
    text-align: left;
}

th {
    color: #94a3b8;
}

footer {
    margin-top: 25px;
    color: #64748b;
    font-size: 12px;
}

@media(max-width: 850px) {
    .grid {
        grid-template-columns: repeat(2, 1fr);
    }
}

@media(max-width: 500px) {
    body {
        padding: 15px;
    }

    .grid {
        grid-template-columns: 1fr 1fr;
        gap: 9px;
    }

    .value {
        font-size: 23px;
    }
}

</style>
</head>

<body>

<header>
    <div>
        <h1>AQUAGIANT</h1>
        <p class="subtitle">
            AI-Powered Smart Aquaculture Monitoring
        </p>
    </div>

    <span class="badge">● SIMULATION MODE</span>
</header>

<div class="grid">

    <div class="card">
        <h3>Water Temperature</h3>
        <div class="value" id="temperature">--</div>
        <span class="unit">°C</span>
    </div>

    <div class="card">
        <h3>Water pH</h3>
        <div class="value" id="ph">--</div>
        <span class="unit">pH level</span>
    </div>

    <div class="card">
        <h3>Dissolved Oxygen</h3>
        <div class="value" id="do">--</div>
        <span class="unit">mg/L</span>
    </div>

    <div class="card">
        <h3>AI Risk Classification</h3>
        <div class="value" id="risk">--</div>
        <span class="unit" id="probability">Awaiting data</span>
    </div>

</div>

<div class="section card">

    <h2>AI Analysis</h2>

    <div id="recommendation">
        Waiting for sensor data...
    </div>

    <p class="subtitle" id="updated">
        Last update: --
    </p>

</div>

<div class="section card">

    <div class="control">
        <div>
            <h2>Aerator Control</h2>
            <p class="subtitle">
                Relay status:
                <strong id="relay">UNKNOWN</strong>
            </p>
        </div>

        <div>
            <button class="on" onclick="controlRelay('ON')">
                TURN ON
            </button>

            <button class="off" onclick="controlRelay('OFF')">
                TURN OFF
            </button>
        </div>
    </div>

</div>

<div class="section card">

    <h2>Sensor History</h2>

    <div style="overflow-x:auto">

        <table>
            <thead>
                <tr>
                    <th>Time</th>
                    <th>Temp</th>
                    <th>pH</th>
                    <th>DO</th>
                    <th>AI Risk</th>
                </tr>
            </thead>

            <tbody id="history">
                <tr>
                    <td colspan="5">Waiting for data...</td>
                </tr>
            </tbody>
        </table>

    </div>

</div>

<footer>
    AQUAGIANT AIoT Prototype · Virtual Sensor Simulation
</footer>

<script>

async function updateDashboard() {

    try {

        const response = await fetch('/api/status');
        const data = await response.json();

        document.getElementById('temperature').textContent =
            data.temperature ?? '--';

        document.getElementById('ph').textContent =
            data.ph ?? '--';

        document.getElementById('do').textContent =
            data.do ?? '--';

        document.getElementById('risk').textContent =
            data.risk ?? '--';

        document.getElementById('probability').textContent =
            data.probability !== null
            ? (data.probability * 100).toFixed(1) + '% risk probability'
            : 'Awaiting data';

        document.getElementById('relay').textContent =
            data.relay;

        document.getElementById('recommendation').textContent =
            data.recommendation;

        document.getElementById('updated').textContent =
            'Last update: ' + (data.updated_at ?? '--');

        const history = data.history || [];

        document.getElementById('history').innerHTML =
            history.slice().reverse().map(item => `
                <tr>
                    <td>${item.time}</td>
                    <td>${item.temperature} °C</td>
                    <td>${item.ph}</td>
                    <td>${item.do} mg/L</td>
                    <td>${item.risk}</td>
                </tr>
            `).join('') || '<tr><td colspan="5">Waiting for data...</td></tr>';

    } catch(error) {
        console.error(error);
    }
}

async function controlRelay(command) {

    try {

        const response = await fetch(
            '/api/manual/' + command,
            { method: 'POST' }
        );

        const result = await response.json();

        if (!result.success) {
            alert(result.message);
        }

        updateDashboard();

    } catch(error) {
        alert('Unable to connect to backend');
    }
}

updateDashboard();

setInterval(updateDashboard, 2000);

</script>

</body>
</html>
"""

