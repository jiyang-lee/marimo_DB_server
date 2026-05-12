#include <PDM.h>

short sampleBuffer[256];
volatile int samplesRead = 0;

void onPDMdata() {
  int bytesAvailable = PDM.available();
  PDM.read(sampleBuffer, bytesAvailable);
  samplesRead = bytesAvailable / 2;
}

void setup() {
  Serial.begin(921600);
  while (!Serial) {}

  PDM.onReceive(onPDMdata);
  if (!PDM.begin(1, 16000)) {
    while (1) {}
  }
}

void loop() {
  if (samplesRead) {
    Serial.write((uint8_t *)sampleBuffer, samplesRead * 2);
    samplesRead = 0;
  }
}
