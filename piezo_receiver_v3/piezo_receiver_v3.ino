// Sends bits with the motor and reads them back with the piezo on the same board.
// Bits are on/off keyed: "1" = motor on for the whole bit, "0" = motor off.
// This sketch only handles 0s and 1s. Encoding and decoding happen in Python.
//
// Same serial commands as piezo_reciever.ino, on the piezo_receiver_v2 hardware.
// Samples A0 continuously with DMA, and all bit timing is counted in samples.
//
// Serial commands (USB, each ending in a newline):
//   B<bits>  send a bit string, e.g. B10110010
//            replies with "<detected>,<vibration>" per bit, then DONE
//   S<ms>    set the settle time, then DONE
//   W<ms>    set the measuring window and recalibrate, then DONE
//   C        recalibrate the threshold, then DONE
//   ?        print the threshold, then READY
// Bad commands reply with a line starting with ERR.
// Vibration and threshold are 16-bit ADC counts (65535 = 3.3 V).
// The motor turns off if the PC closes the port.
//
// Wiring:
//   Front-end ADC node (after R5/C3/clamps) -> A0
//   Driver Signal -> D3, driver GND -> GIGA GND, driver V+ NOT connected to the GIGA
//   Motor powered from its own supply via the driver's terminal blocks
//
// Requires: Arduino_AdvancedAnalog (Library Manager), board "Arduino GIGA R1 WiFi" (M7 core).

#include <Arduino_AdvancedAnalog.h>

const int MOTOR_PIN = 3;

// ADC. Each DMA buffer holds N_SAMPLES / SAMPLE_RATE = 25.6 ms of samples.
const uint32_t SAMPLE_RATE = 10000;   // Hz
const size_t N_SAMPLES = 256;         // per DMA buffer
const size_t N_BUFFERS = 32;          // queue depth, 0.8 s of slack
const uint32_t SAMPLES_PER_MS = SAMPLE_RATE / 1000;
const uint32_t ADC_WARMUP_MS = 200;   // ignored after starting the ADC

// Timing. The motor can only switch when a buffer arrives, so each bit takes
// settleMs + windowMs rounded up to a whole number of buffers (200 ms -> 204.8 ms).
const unsigned long CALIBRATION_MS = 3000;
unsigned long settleMs = 100;   // wait for the motor to spin up or down
unsigned long windowMs = 100;   // measure the piezo for this long

// Noise detection
const int NOISE_MARGIN = 3000;  // 16-bit counts, about 150 mV (set for the big piezo)
int threshold = 0;

// Incoming command, with room for "B" plus 1000 bits
const unsigned int MAX_LINE = 1001;
String line;
bool lineTooLong = false;

AdvancedADC adc(A0);

// Throw away finished buffers. When the queue is full the ADC stops adding to it,
// so anything left unread would later be measured as if it were new.
void drainAdc() {

  while (adc.available()) {
    SampleBuffer buffer = adc.read();
    buffer.release();
  }
}

// Return just as a new buffer starts, so that a motor switch made right after
// this has no older samples ahead of it.
void syncToBuffer() {

  drainAdc();

  SampleBuffer buffer = adc.read();   // waits for the next one
  buffer.release();
}

// Skip some samples, then measure peak-to-peak vibration over the next ones
int measureVibration(uint32_t skipSamples, uint32_t windowSamples) {

  int minValue = 65535;
  int maxValue = 0;

  while (windowSamples > 0) {

    SampleBuffer buffer = adc.read();   // waits for the next one
    size_t count = buffer.size();

    for (size_t i = 0; i < count && windowSamples > 0; i++) {

      if (skipSamples > 0) {
        skipSamples--;
        continue;
      }

      int value = buffer[i];

      if (value < minValue) minValue = value;
      if (value > maxValue) maxValue = value;

      windowSamples--;
    }

    buffer.release();
  }

  return maxValue - minValue;
}

// Set the threshold from the background noise, with the motor off
void calibrate() {

  digitalWrite(MOTOR_PIN, LOW);

  Serial.println("Calibrating...");
  Serial.println("Keep the surface still!");

  syncToBuffer();

  unsigned long start = millis();
  int maximumNoise = 0;

  while (millis() - start < CALIBRATION_MS) {

    int noise = measureVibration(0, windowMs * SAMPLES_PER_MS);

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

  syncToBuffer();

  for (unsigned int i = 0; i < bits.length(); i++) {

    // Port closed, so nobody is listening any more
    if (!Serial) {
      digitalWrite(MOTOR_PIN, LOW);
      return;
    }

    digitalWrite(MOTOR_PIN, bits[i] == '1' ? HIGH : LOW);

    int vibration = measureVibration(settleMs * SAMPLES_PER_MS, windowMs * SAMPLES_PER_MS);
    int detected = (vibration >= threshold) ? 1 : 0;

    Serial.print(detected);
    Serial.print(",");
    Serial.println(vibration);

    // Normally the last buffer has only just been read. If printing was held up
    // the queue has older samples in it, so catch up before the next bit.
    if (adc.available()) {
      syncToBuffer();
    }
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

  pinMode(MOTOR_PIN, OUTPUT);
  digitalWrite(MOTOR_PIN, LOW);   // motor off while booting

  Serial.begin(115200);           // USB: the baud value is ignored
  while (!Serial) {}              // wait for the PC to open the port

  line.reserve(MAX_LINE);

  if (!adc.begin(AN_RESOLUTION_16, SAMPLE_RATE, N_SAMPLES, N_BUFFERS)) {
    Serial.println("ERR ADC failed to start");
    while (1) {}
  }

  measureVibration(ADC_WARMUP_MS * SAMPLES_PER_MS, 1);

  calibrate();

  Serial.println("READY");
}

void loop() {

  // A half-received command is no use once the port has closed
  if (!Serial) {
    line = "";
    lineTooLong = false;
  }

  drainAdc();

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
