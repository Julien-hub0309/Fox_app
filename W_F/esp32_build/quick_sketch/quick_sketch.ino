// Affiche les infos de la puce puis ne fait plus rien
void setup() {
  Serial.begin(115200);
  delay(1500);
  Serial.printf("Puce : %s (rev %d)\n", ESP.getChipModel(), (int)ESP.getChipRevision());
  Serial.printf("Coeurs : %d @ %d MHz\n", (int)ESP.getChipCores(), (int)ESP.getCpuFreqMHz());
  Serial.printf("Flash : %u Mo\n", (unsigned)(ESP.getFlashChipSize() / (1024 * 1024)));
  Serial.printf("RAM libre : %u octets\n", (unsigned)ESP.getFreeHeap());
  Serial.printf("MAC : %llX\n", ESP.getEfuseMac());
}

void loop() {}
