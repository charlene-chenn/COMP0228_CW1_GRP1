// Piezo reader + motor control for Arduino GIGA R1 WiFi
//
// Samples A0 continuously with DMA (Arduino_AdvancedAnalog) while switching the
// vibration motor through the Adafruit STEMMA MOSFET driver. Both run off the same
// sample clock, so the motor timing in mode 2 never drifts relative to the samples.
//
// Motor mode is set at runtime by sending one character over serial:
//   '0' = motor off          (noise floor)
//   '1' = motor on           (amplitude, motor frequency)
//   '2' = 1 s on / 1 s off   (step response, OOK preview); starts with ON
// capture.py sends this automatically when given its MOTOR_MODE argument.
// In plotter mode you can type 0/1/2 into the Serial Monitor/Plotter input box.
// The motor turns OFF whenever the PC closes the port.
//
// Output (choose with OUTPUT_MODE):
//   MODE_BINARY  : raw samples for capture.py
//                  frame = [0xA5 0x5A] [uint32 counter] [N_SAMPLES x uint16], little-endian
//   MODE_PLOTTER : per-buffer min/mean/max volts + motor state, for the Serial Plotter
//
// Wiring:
//   Front-end ADC node (after R5/C3/clamps) -> A0
//   Driver Signal -> D3, driver GND -> GIGA GND, driver V+ NOT connected to the GIGA
//   Motor powered from its own supply via the driver's terminal blocks
//
// Requires: Arduino_AdvancedAnalog (Library Manager), board "Arduino GIGA R1 WiFi" (M7 core).

#include <Arduino_AdvancedAnalog.h>

// ---------------- Configuration ----------------
#define MODE_PLOTTER 0
#define MODE_BINARY  1
const int OUTPUT_MODE = MODE_PLOTTER;      // MODE_BINARY for capture.py

const uint32_t SAMPLE_RATE = 10000;       // Hz; must match FS in capture.py
const size_t   N_SAMPLES   = 256;         // per DMA buffer; must match N in capture.py
const size_t   N_BUFFERS   = 32;          // queue depth (32 x 25.6 ms = 0.8 s of slack)

const int      MOTOR_PIN           = 3;
const int      DEFAULT_MOTOR_MODE  = 0;   // mode on connect if no command is sent
const uint32_t HALF_PERIOD_SAMPLES = SAMPLE_RATE;  // mode 2: 1 s on, 1 s off

const float VREF       = 3.3f;
const float FULL_SCALE = 65535.0f;        // 16-bit

// ---------------- State ----------------
AdvancedADC adc(A0);

static uint16_t frame_samples[N_SAMPLES];
static uint32_t counter = 0;
static const uint8_t SYNC[2] = {0xA5, 0x5A};

static int      motor_mode    = DEFAULT_MOTOR_MODE;
static bool     motor_on      = false;
static uint64_t samples_total = 0;        // samples read since power-up
static uint64_t mode_start    = 0;        // sample index of the last mode change

// ---------------- Motor ----------------
void setMotor(bool on) {
  motor_on = on;
  digitalWrite(MOTOR_PIN, on ? HIGH : LOW);
}

void setMotorMode(int mode) {
  motor_mode = mode;
  mode_start = samples_total;
  setMotor(mode != 0);                    // modes 1 and 2 both start ON
}

// Mode 2 timing is counted in samples, not millis(), so it is locked to the ADC clock.
// The motor can only switch when a buffer is read, so edges land on buffer boundaries
// (every N_SAMPLES / SAMPLE_RATE = 25.6 ms) and about one buffer after the nominal
// time. Find the real edges in the recorded data rather than assuming them.
void updateMotor() {
  if (motor_mode != 2) return;
  uint64_t elapsed = samples_total - mode_start;
  bool on = ((elapsed / HALF_PERIOD_SAMPLES) % 2) == 0;
  if (on != motor_on) setMotor(on);
}

void handleCommands() {
  while (Serial.available() > 0) {
    int c = Serial.read();
    if (c >= '0' && c <= '2') setMotorMode(c - '0');   // ignore newlines etc.
  }
}

// ---------------- Main ----------------
void setup() {
  pinMode(MOTOR_PIN, OUTPUT);
  setMotor(false);                        // motor off while booting

  Serial.begin(2000000);                  // USB CDC: the baud value is ignored
  while (!Serial) {}                      // wait for the PC to open the port

  if (!adc.begin(AN_RESOLUTION_16, SAMPLE_RATE, N_SAMPLES, N_BUFFERS)) {
    while (1) {
      if (OUTPUT_MODE == MODE_PLOTTER) Serial.println("ADC failed to start");
      delay(1000);
    }
  }
  setMotorMode(DEFAULT_MOTOR_MODE);
}

void loop() {
  // Motor off when the port closes; back to the default mode when it reopens
  static bool connected = true;
  if (!Serial) {
    if (connected) {
      setMotor(false);
      motor_mode = 0;
      connected = false;
    }
    if (adc.available()) {                // keep draining so the queue doesn't back up
      SampleBuffer b = adc.read();
      b.release();
    }
    return;
  }
  if (!connected) {
    connected = true;
    setMotorMode(DEFAULT_MOTOR_MODE);
  }

  handleCommands();

  if (!adc.available()) return;

  SampleBuffer buf = adc.read();
  size_t n = buf.size();
  if (n > N_SAMPLES) n = N_SAMPLES;
  for (size_t i = 0; i < n; i++) {
    frame_samples[i] = buf[i];
  }
  buf.release();                          // return the DMA buffer as early as possible

  samples_total += n;
  updateMotor();

  if (OUTPUT_MODE == MODE_BINARY) {
    Serial.write(SYNC, 2);
    Serial.write((const uint8_t*)&counter, 4);
    Serial.write((const uint8_t*)frame_samples, n * 2);
    counter++;
    return;
  }

  // Plotter mode: one line per buffer (~39 lines/s)
  uint16_t lo = 65535, hi = 0;
  uint32_t sum = 0;
  for (size_t i = 0; i < n; i++) {
    uint16_t v = frame_samples[i];
    if (v < lo) lo = v;
    if (v > hi) hi = v;
    sum += v;
  }
  float k = VREF / FULL_SCALE;
  Serial.print("min:");    Serial.print(lo * k, 4);
  Serial.print(",mean:");  Serial.print((sum / (float)n) * k, 4);
  Serial.print(",max:");   Serial.print(hi * k, 4);
  Serial.print(",motor:"); Serial.println(motor_on ? 1 : 0);
}