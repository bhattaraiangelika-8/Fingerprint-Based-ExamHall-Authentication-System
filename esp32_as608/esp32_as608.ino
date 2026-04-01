#include <WiFi.h>
#include <HTTPClient.h>

// ============ CONFIG ============
#define WIFI_SSID     "Khwopa"
#define WIFI_PASS     "khwop@123"
#define SERVER_PORT   5000

String serverIP = "192.168.1.71";  // Change via serial: send "ip=192.168.1.50"

#define AS608_RX      16
#define AS608_TX      17
#define TOUCH_PIN     4
#define AS608_BAUD    57600

// ============ AS608 PROTOCOL ============

#define HEADER_0      0xEF
#define HEADER_1      0x01
#define PID_CMD       0x01
#define PID_DATA      0x02
#define PID_ACK       0x07
#define PID_EOD       0x08

#define CMD_CAPTURE_FINGER         0x01
#define CMD_CAPTURE_FINGER_LED_OFF 0x52
#define CMD_READ_IMAGE_BUFFER      0x0A

#define ACK_SUCCESS              0x00
#define ACK_NO_FINGER            0x02
#define ACK_CAPTURE_FAILED       0x03

#define IMAGE_SIZE     36864  // 288*256/2
#define DATA_PACKET_SZ 128    // default data packet content size

static uint8_t moduleAddr[4] = {0xFF, 0xFF, 0xFF, 0xFF};
uint8_t imageBuffer[IMAGE_SIZE];

void sendPacket(uint8_t pid, const uint8_t* content, uint16_t contentLen) {
    uint16_t length = contentLen + 2;
    uint8_t header[7] = {HEADER_0, HEADER_1,
                         moduleAddr[0], moduleAddr[1], moduleAddr[2], moduleAddr[3],
                         pid};
    Serial2.write(header, 7);
    Serial2.write((uint8_t)(length >> 8));
    Serial2.write((uint8_t)(length & 0xFF));
    Serial2.write(content, contentLen);
    uint16_t checksum = pid + (length >> 8) + (length & 0xFF);
    for (uint16_t i = 0; i < contentLen; i++) checksum += content[i];
    Serial2.write((uint8_t)(checksum >> 8));
    Serial2.write((uint8_t)(checksum & 0xFF));
    Serial2.flush();
}

bool readExact(uint8_t* buf, size_t count) {
    size_t total = 0;
    unsigned long start = millis();
    while (total < count) {
        if (Serial2.available()) {
            buf[total++] = Serial2.read();
        }
        if (millis() - start > 1000) return false;
    }
    return true;
}

int8_t readAck() {
    uint8_t buf[12];
    if (!readExact(buf, 12)) return -1;
    if (buf[0] != HEADER_0 || buf[1] != HEADER_1) return -1;
    if (memcmp(buf + 2, moduleAddr, 4) != 0) return -1;
    if (buf[6] != PID_ACK) return -1;
    return buf[9];  // confirmation code
}

bool captureFinger(bool ledOn = true) {
    uint8_t cmd = ledOn ? CMD_CAPTURE_FINGER : CMD_CAPTURE_FINGER_LED_OFF;
    sendPacket(PID_CMD, &cmd, 1);
    int8_t ack = readAck();
    if (ack < 0) return false;
    return ack == ACK_SUCCESS;
}

bool readImageBuffer() {
    uint8_t cmd = CMD_READ_IMAGE_BUFFER;
    sendPacket(PID_CMD, &cmd, 1);

    int8_t ack = readAck();
    if (ack != ACK_SUCCESS) return false;

    // Receive data packets until EOD
    uint32_t offset = 0;
    while (true) {
        uint8_t pkt[11 + DATA_PACKET_SZ];
        if (!readExact(pkt, 11 + DATA_PACKET_SZ)) return false;

        uint8_t pid = pkt[6];
        uint16_t length = ((uint16_t)pkt[7] << 8) | pkt[8];
        uint16_t contentLen = length - 2;

        memcpy(imageBuffer + offset, pkt + 9, contentLen);
        offset += contentLen;

        if (pid == PID_EOD) break;
        if (pid != PID_DATA) return false;
    }
    return (offset == IMAGE_SIZE);
}

// ============ TOUCH DETECTION ============

volatile bool touchDetected = false;
unsigned long lastCaptureTime = 0;

void IRAM_ATTR onTouch() {
    touchDetected = true;
}

// ============ WIFI UPLOAD ============

bool sendImageToServer() {
    if (WiFi.status() != WL_CONNECTED) {
        Serial.println("WiFi not connected, reconnecting...");
        WiFi.reconnect();
        delay(3000);
        if (WiFi.status() != WL_CONNECTED) return false;
    }

    HTTPClient http;
    String url = "http://" + serverIP + ":" + String(SERVER_PORT) + "/upload";
    http.begin(url);
    http.addHeader("Content-Type", "application/octet-stream");

    int code = http.POST(imageBuffer, IMAGE_SIZE);
    http.end();

    if (code == 200) {
        Serial.println("Image uploaded successfully.");
        return true;
    } else {
        Serial.printf("Upload failed, HTTP code: %d\n", code);
        return false;
    }
}

// ============ MAIN ============

void setup() {
    Serial.begin(115200);
    Serial.println("\n=== AS608 ESP32 Client ===");

    pinMode(TOUCH_PIN, INPUT);
    attachInterrupt(TOUCH_PIN, onTouch, RISING);

    Serial2.begin(AS608_BAUD, SERIAL_8N1, AS608_RX, AS608_TX);

    WiFi.begin(WIFI_SSID, WIFI_PASS);
    Serial.print("Connecting to WiFi");
    while (WiFi.status() != WL_CONNECTED) {
        delay(500);
        Serial.print(".");
    }
    Serial.printf("\nConnected! IP: %s\n", WiFi.localIP().toString().c_str());
    Serial.printf("Target server: http://%s:%d\n", serverIP.c_str(), SERVER_PORT);
    Serial.println("Commands: 'c'=capture  'ip=x.x.x.x'=set server IP");
    Serial.println("Waiting for finger touch on GPIO4...");
}

void loop() {
    if (touchDetected && millis() - lastCaptureTime > 2000) {
        touchDetected = false;
        lastCaptureTime = millis();

        Serial.println("Touch detected! Capturing...");

        if (!captureFinger(true)) {
            Serial.println("Capture failed.");
            return;
        }
        Serial.println("Finger captured. Reading image...");

        if (!readImageBuffer()) {
            Serial.println("Failed to read image buffer.");
            return;
        }
        Serial.println("Image read complete. Uploading...");

        sendImageToServer();
    }

    // Manual commands via serial
    if (Serial.available()) {
        String cmd = Serial.readStringUntil('\n');
        cmd.trim();

        if (cmd == "c") {
            Serial.println("Manual capture triggered.");
            if (captureFinger(true) && readImageBuffer()) {
                sendImageToServer();
            } else {
                Serial.println("Capture or read failed.");
            }
        } else if (cmd.startsWith("ip=")) {
            serverIP = cmd.substring(3);
            Serial.printf("Server IP set to: %s\n", serverIP.c_str());
        }
    }
}
