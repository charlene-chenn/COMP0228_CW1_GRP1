// Sends bits with the motor and reads them back with the piezo on the same board.
// Bits are on/off keyed: "1" = motor on for the whole bit, "0" = motor off.
// This sketch only handles 0s and 1s. Encoding and decoding happen in Python.
//
// Serial commands (115200 baud, each ending in a newline):
//   B<bits>  send a bit string, e.g. B10110010
//            replies with "<detected>,<vibration>" per bit, then DONE
//   S<ms>    set the settle time, then DONE
//   W<ms>    set the measuring window and recalibrate, then DONE
//   C        recalibrate the threshold, then DONE
//   ?        print the threshold, then READY
// Bad commands reply with a line starting with ERR.

const int SENSOR_PIN = A0;
const int MOTOR_PIN = 8;

// Timing. Each bit takes about settleMs + windowMs.
const unsigned long CALIBRATION_MS = 3000;
unsigned long settleMs = 100;   // wait for the motor to spin up or down
unsigned long windowMs = 100;   // measure the piezo for this long

// Noise detection
const int NOISE_MARGIN = 10;
int threshold = 0;

// Incoming command, with room for "B" plus 1000 bits
const unsigned int MAX_LINE = 1001;
String line;
bool lineTooLong = false;

// Measure peak-to-peak vibration
int measureVibration(unsigned long duration) {

  int minValue = 1023;
  int maxValue = 0;

  unsigned long startTime = millis();

  while (millis() - startTime < duration) {

    int value = analogRead(SENSOR_PIN);

    if (value < minValue) minValue = value;
    if (value > maxValue) maxValue = value;
  }

  return maxValue - minValue;
}

// Set the threshold from the background noise, with the motor off
void calibrate() {

  digitalWrite(MOTOR_PIN, LOW);

  Serial.println("Calibrating...");
  Serial.println("Keep the surface still!");

  unsigned long start = millis();
  int maximumNoise = 0;

  while (millis() - start < CALIBRATION_MS) {

    int noise = measureVibration(windowMs);

    if (noise > maximumNoise) {
      maximumNoise = noise;
    }
  }

  threshold = maximumNoise + NOISE_MARGIN;

  Serial.print("Noise floor: ");
  Serial.println(maximumNoise);

  Serial.print("Threshold: ");
  Serial.println(threshold);

  Serial.println("Calibration complete.");
}

// Transmit each bit and measure what the piezo picks up during it
void sendBits(const String &bits) {

  // Check the whole string first, so a bad one never moves the motor
  for (unsigned int i = 0; i < bits.length(); i++) {
    if (bits[i] != '0' && bits[i] != '1') {
      Serial.println("ERR bits must be 0 or 1");
      return;
    }
  }

  for (unsigned int i = 0; i < bits.length(); i++) {

    digitalWrite(MOTOR_PIN, bits[i] == '1' ? HIGH : LOW);
    delay(settleMs);

    int vibration = measureVibration(windowMs);
    int detected = (vibration >= threshold) ? 1 : 0;

    Serial.print(detected);
    Serial.print(",");
    Serial.println(vibration);
  }

  digitalWrite(MOTOR_PIN, LOW);
  Serial.println("DONE");
}

void handleCommand(const String &command) {

  if (command.length() == 0) return;

  char type = command[0];
  String argument = command.substring(1);

  if (type == 'B') {
    sendBits(argument);

  } else if (type == 'S') {
    long value = argument.toInt();
    if (value < 0) {
      Serial.println("ERR settle time must be 0 or more");
      return;
    }
    settleMs = value;
    Serial.println("DONE");

  } else if (type == 'W') {
    long value = argument.toInt();
    if (value < 1) {
      Serial.println("ERR window must be at least 1");
      return;
    }
    windowMs = value;
    // A longer window sees larger peaks, so the old threshold no longer applies
    calibrate();
    Serial.println("DONE");

  } else if (type == 'C') {
    calibrate();
    Serial.println("DONE");

  } else if (type == '?') {
    Serial.print("Threshold: ");
    Serial.println(threshold);
    Serial.println("READY");

  } else {
    Serial.println("ERR unknown command");
  }
}

void setup() {

  Serial.begin(115200);
  analogReadResolution(10);

  pinMode(SENSOR_PIN, INPUT);
  pinMode(MOTOR_PIN, OUTPUT);

  line.reserve(MAX_LINE);

  calibrate();

  Serial.println("READY");
}

void loop() {

  while (Serial.available()) {

    char ch = Serial.read();

    if (ch == '\n') {
      if (lineTooLong) {
        Serial.println("ERR command too long");
      } else {
        handleCommand(line);
      }
      line = "";
      lineTooLong = false;

    } else if (ch != '\r') {
      if (line.length() < MAX_LINE) {
        line += ch;
      } else {
        lineTooLong = true;
      }
    }
  }
}
