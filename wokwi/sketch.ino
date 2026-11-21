
#include <WiFi.h>
#include <PubSubClient.h>

// Made by CREATEVA


// GPIO
#define PH_PIN 34
#define DO_PIN 35
#define TEMP_PIN 32
#define RELAY_PIN 26

// Relay active LOW
#define RELAY_ON LOW
#define RELAY_OFF HIGH

// WiFi Wokwi
const char* WIFI_SSID = "Wokwi-GUEST";
const char* WIFI_PASSWORD = "";

// MQTT DEMO BROKER
const char* MQTT_HOST = "broker.hivemq.com";
const int MQTT_PORT = 1883;

// MQTT Topics
const char* TOPIC_DATA =
  "aquagiant/team01/pond01/data";

const char* TOPIC_COMMAND =
  "aquagiant/team01/pond01/command";

const char* TOPIC_STATUS =
  "aquagiant/team01/pond01/status";




// MQTT client
WiFiClient wifiClient;
PubSubClient mqtt(wifiClient);
// -----


// data Sensor
float phValue = 7.0;
float doValue = 6.0;
float temperature = 28.0;

bool relayState = false;

unsigned long lastPublish = 0;
unsigned long lastWiFiAttempt = 0;
unsigned long lastMQTTAttempt = 0;

const unsigned long PUBLISH_INTERVAL = 3000;
// -----


// Control Relay

void setRelay(bool state) {

  if (relayState == state) {
    return;
  }

  relayState = state;

  digitalWrite(
    RELAY_PIN,
    state ? RELAY_ON : RELAY_OFF
  );

  Serial.println(
    state ? "AERATOR ON" : "AERATOR OFF"
  );

  if (mqtt.connected()) {
    mqtt.publish(
      TOPIC_STATUS,
      state ? "ON" : "OFF",
      true
    );
  }
}
// -----


// Sensor

void readSensors() {
  int phRaw = analogRead(PH_PIN);
  int doRaw = analogRead(DO_PIN);
  int tempRaw = analogRead(TEMP_PIN);

  // Mapping untuk simulasi Wokwi
  phValue = (phRaw / 4095.0) * 14.0;

  doValue = (doRaw / 4095.0) * 12.0;

  temperature =
    15.0 + (tempRaw / 4095.0) * 25.0;

  // Limit output
  phValue = constrain(phValue, 0, 14);
  doValue = constrain(doValue, 0, 12);
  temperature = constrain(temperature, 15, 40);
}
// -----


// Callback MQTT

void mqttCallback(
  char* topic,
  byte* payload,
  unsigned int length
) {
  String command = "";

  for (unsigned int i = 0; i < length; i++) {
    command += (char)payload[i];
  }

  command.trim();

  Serial.print("AI COMMAND: ");
  Serial.println(command);

  if (command == "ON") {
    setRelay(true);
  }

  else if (command == "OFF") {
    // Safety interlock
    if (doValue > 5.0) {
      setRelay(false);
    } else {
      setRelay(true);
      Serial.println(
        "OFF rejected: DO still low"
      );
    }
  }
}
// ---------


// Wifi

void connectWiFi() {
  if (WiFi.status() == WL_CONNECTED) {
    return;
  }

  unsigned long now = millis();

  if (now - lastWiFiAttempt < 5000) {
    return;
  }

  lastWiFiAttempt = now;

  Serial.println("Connecting WiFi...");

  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
}
// --------


// MQTT

void connectMQTT() {
  if (mqtt.connected() ||
      WiFi.status() != WL_CONNECTED) {
    return;
  }

  unsigned long now = millis();

  if (now - lastMQTTAttempt < 3000) {
    return;
  }

  lastMQTTAttempt = now;

  String clientId =
    "AquaGiant-" +
    String(random(0xffff), HEX);

  Serial.println("Connecting MQTT...");

  if (mqtt.connect(clientId.c_str())) {
    Serial.println("MQTT Connected!");

    mqtt.subscribe(TOPIC_COMMAND);

    mqtt.publish(
      TOPIC_STATUS,
      relayState ? "ON" : "OFF",
      true
    );
  } else {
    Serial.print("MQTT Error: ");
    Serial.println(mqtt.state());
  }
}
// -------


// Publish data sensor

void publishData() {
  char payload[200];

  snprintf(
    payload,
    sizeof(payload),
    "{\"temperature\":%.2f,"
    "\"ph\":%.2f,"
    "\"do\":%.2f}",
    temperature,
    phValue,
    doValue
  );

  mqtt.publish(TOPIC_DATA, payload);

  Serial.println(payload);
}
// ------

// Setup

void setup() {
  Serial.begin(115200);

  pinMode(RELAY_PIN, OUTPUT);

  digitalWrite(RELAY_PIN, RELAY_OFF);

  analogReadResolution(12);

  mqtt.setServer(MQTT_HOST, MQTT_PORT);
  mqtt.setCallback(mqttCallback);

  mqtt.setBufferSize(256);

  WiFi.mode(WIFI_STA);
  connectWiFi();

  Serial.println("AQUAGIANT STARTED");
}
// -------


// Loop

void loop() {
  connectWiFi();
  connectMQTT();

  if (mqtt.connected()) {
    mqtt.loop();
  }

  readSensors();

  // Local safety: DO very low
  if (doValue < 3.5) {
    setRelay(true);
  }

  unsigned long now = millis();

  if (now - lastPublish >= PUBLISH_INTERVAL) {
    lastPublish = now;

    Serial.println("----- AQUAGIANT -----");
    Serial.printf("pH: %.2f\n", phValue);
    Serial.printf("DO: %.2f mg/L\n", doValue);
    Serial.printf("Temperature: %.2f C\n", temperature);

    if (mqtt.connected()) {
      publishData();
    }
  }

  delay(50);
}
