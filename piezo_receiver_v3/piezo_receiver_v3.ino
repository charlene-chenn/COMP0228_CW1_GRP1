// Sends bits with the motor and reads them back with the piezo on the same board.
// Bits are on/off keyed: "1" = motor on for the whole bit, "0" = motor off.
// Encoding and decoding happen in Python.
//
// Samples A0 continuously with DMA, and all bit timing is counted in samples.
//
// Serial commands (USB, each ending in a newline):
//   B<bits>  send a bit string, e.g. B10110010
//            replies with "<detected>,<vibration>" per bit, then "Late: <n>", then DONE
//   R1 / R0  turn raw sample streaming on / off (off at start), then DONE
//   S<ms>    set the settle time, then DONE
//   W<ms>    set the measuring window and recalibrate, then DONE
//   C        recalibrate the threshold, then DONE
//   ?        print the threshold, then READY
// Bad commands reply with a line starting with ERR.
//
// With raw streaming on, each bit's "<detected>,<vibration>" line comes straight
// after "R<count>,<offset>" and then <count> samples as raw binary (uint16,
// little-endian, 2 bytes each). These are every sample in the buffers read for
// that bit, so consecutive bits join up into one continuous recording unless a
// catch-up happened. <offset> is how many samples into the bit's first buffer
// the motor was switched (it counts the time spent printing the previous bit).
// "Late: <n>" counts the bits after which printing ran into the next buffer, so
// the board had to skip ahead. Those bits ran longer than usual, and the raw
// recording has a gap after them.
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

// Raw streaming. 16384 samples covers bits up to 1.6 s long, longer bits are cut short.
const size_t MAX_RAW_SAMPLES = 16384;
uint16_t rawSamples[MAX_RAW_SAMPLES];
size_t rawCount = 0;
bool rawMode = false;
const long BUFFER_US = (long)N_SAMPLES * 1000000L / SAMPLE_RATE;  // 25600 us

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

// Skip some samples, then measure peak-to-peak vibration over the next ones.
// If keepRaw is set, every sample of every buffer read is copied to rawSamples,
// and firstBufferDone is set to when the first buffer finished (micros).
int measureVibration(uint32_t skipSamples, uint32_t windowSamples,
                     bool keepRaw = false, unsigned long *firstBufferDone = nullptr) {

  int minValue = 65535;
  int maxValue = 0;
  bool first = true;

  if (keepRaw) rawCount = 0;

  while (windowSamples > 0) {

    SampleBuffer buffer = adc.read();   // waits for the next one
    size_t count = buffer.size();

    if (first && firstBufferDone != nullptr) *firstBufferDone = micros();
    first = false;

    if (keepRaw) {
      for (size_t i = 0; i < count && rawCount < MAX_RAW_SAMPLES; i++) {
        rawSamples[rawCount++] = buffer[i];
      }
    }

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
  int late = 0;

  for (unsigned int i = 0; i < bits.length(); i++) {

    // Port closed, so nobody is listening any more
    if (!Serial) {
      digitalWrite(MOTOR_PIN, LOW);
      return;
    }

    digitalWrite(MOTOR_PIN, bits[i] == '1' ? HIGH : LOW);
    unsigned long switchedAt = micros();
    unsigned long firstBufferDone = switchedAt;

    int vibration = measureVibration(settleMs * SAMPLES_PER_MS, windowMs * SAMPLES_PER_MS,
                                     rawMode, &firstBufferDone);
    int detected = (vibration >= threshold) ? 1 : 0;

    if (rawMode) {
      // The first buffer started BUFFER_US before it finished
      long offsetUs = (long)(switchedAt - firstBufferDone) + BUFFER_US;
      Serial.print("R");
      Serial.print(rawCount);
      Serial.print(",");
      Serial.println(offsetUs * (long)SAMPLE_RATE / 1000000L);
      Serial.write((const uint8_t *)rawSamples, rawCount * sizeof(uint16_t));
    }

    Serial.print(detected);
    Serial.print(",");
    Serial.println(vibration);

    // Normally the last buffer has only just been read. If printing was held up
    // the queue has older samples in it, so catch up before the next bit.
    if (adc.available()) {
      syncToBuffer();
      late++;
    }
  }

  digitalWrite(MOTOR_PIN, LOW);
  Serial.print("Late: ");
  Serial.println(late);
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

  } else if (type == 'R') {
    if (argument != "0" && argument != "1") {
      Serial.println("ERR use R1 or R0");
      return;
    }
    rawMode = (argument == "1");
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
