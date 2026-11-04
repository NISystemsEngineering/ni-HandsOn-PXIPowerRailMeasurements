   #include "esp_sleep.h"
   #include "esp_log.h"

   void app_main(void) {
       ESP_LOGI("SLEEP_FOREVER", "Entering permanent deep sleep. Reflash to exit.");
       esp_deep_sleep_start();
   }