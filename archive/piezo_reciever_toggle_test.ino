
const int SENSOR_PIN = A0;
const int MOTOR_PIN = 8;

// Timing
const unsigned long WINDOW_MS = 100;
const unsigned long CALIBRATION_MS = 3000;
const unsigned long MOTOR_INTERVAL = 1000;

// Noise detection
const int NOISE_MARGIN = 10;
int threshold = 0;

// Motor control
bool motorState = false;
unsigned long lastMotorChange = 0;

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

void setup() {

  Serial.begin(115200);
  analogReadResolution(10);

  pinMode(SENSOR_PIN, INPUT);
  pinMode(MOTOR_PIN, OUTPUT);

  // Keep motor OFF during calibration
  digitalWrite(MOTOR_PIN, LOW);

  Serial.println("Calibrating...");
  Serial.println("Keep the surface still!");

  unsigned long start = millis();
  int maximumNoise = 0;

  while (millis() - start < CALIBRATION_MS) {

    int noise = measureVibration(WINDOW_MS);

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

  // Start motor ON
  motorState = true;
  digitalWrite(MOTOR_PIN, HIGH);
  lastMotorChange = millis();

  Serial.println("Motor,Detected,Vibration,Threshold");
}

void loop() {

  unsigned long currentTime = millis();

  // Switch motor every 1000 ms
  if (currentTime - lastMotorChange >= MOTOR_INTERVAL) {

    motorState = !motorState;

    digitalWrite(MOTOR_PIN, motorState ? HIGH : LOW);

    lastMotorChange = currentTime;
  }

  // Measure piezo vibration
  int vibration = measureVibration(WINDOW_MS);

  int detected = (vibration >= threshold) ? 1 : 0;

  // Print CSV data
  Serial.print(motorState ? 1 : 0);
  Serial.print(",");

  Serial.print(detected);
  Serial.print(",");

  Serial.print(vibration);
  Serial.print(",");

  Serial.println(threshold);
}
