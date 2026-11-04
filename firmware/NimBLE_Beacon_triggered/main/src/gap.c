/*
 * SPDX-FileCopyrightText: 2024 Espressif Systems (Shanghai) CO LTD
 *
 * SPDX-License-Identifier: Unlicense OR CC0-1.0
 *
 * MODIFIED:
 * 1) Manually re-armed single-shot advertising events (instead of continuous
 *    BLE_HS_FOREVER advertising) so a GPIO marker can be toggled immediately
 *    before each 3-channel advertising event. This lets an external scope/SMU
 *    trigger off the GPIO edge to correlate exactly with the RF burst, rather
 *    than guessing from a current-threshold trigger.
 * 2) Forced non-scannable advertising (ADV_NONCONN_IND) so the DUT never opens
 *    a post-ADV RX window or transmits SCAN_RSP. In busy RF environments, active
 *    scanners were eliciting unpredictable scan responses that made rail voltage
 *    and current captures jumpy; quiet lab benches rarely saw that activity.
 */
/* Includes */
#include "gap.h"
#include "common.h"
#include "driver/gpio.h"
 
/* ---- Marker / timing configuration ---- */
#define ADV_MARKER_GPIO      GPIO_NUM_10   /* pick an unused header pin */
#define ADV_EVENT_DURATION_MS 10          /* short enough to cover one 3-ch burst */
#define ADV_PERIOD_MS         150         /* total time between burst-set starts;
                                              adjust to match/compare against the
                                              beacon's original ~130-150 ms interval */
 
/* Private function declarations */
inline static void format_addr(char *addr_str, uint8_t addr[]);
static void start_advertising(void);
static int gap_event_handler(struct ble_gap_event *event, void *arg);
static void init_marker_gpio(void);
 
/* Private variables */
static uint8_t own_addr_type;
static uint8_t addr_val[6] = {0};

/* Private functions */
inline static void format_addr(char *addr_str, uint8_t addr[]) {
    sprintf(addr_str, "%02X:%02X:%02X:%02X:%02X:%02X", addr[0], addr[1],
            addr[2], addr[3], addr[4], addr[5]);
}
 
static void init_marker_gpio(void) {
    gpio_config_t io_conf = {
        .pin_bit_mask = (1ULL << ADV_MARKER_GPIO),
        .mode = GPIO_MODE_OUTPUT,
        .pull_up_en = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    gpio_config(&io_conf);
    gpio_set_level(ADV_MARKER_GPIO, 0);
}
 
/*
 * Fires when a single advertising event (the 3-channel burst set) completes.
 * Drops the marker low, waits out the remainder of the desired interval,
 * then re-arms the next event. Running the delay in this task keeps the
 * marker/re-arm logic simple; for tighter interval accuracy this could be
 * moved to an esp_timer callback instead of vTaskDelay.
 */
static int gap_event_handler(struct ble_gap_event *event, void *arg) {
    switch (event->type) {
        case BLE_GAP_EVENT_ADV_COMPLETE:
            gpio_set_level(ADV_MARKER_GPIO, 0);
 
            /* Wait out the remainder of the period before the next burst set.
               ADV_EVENT_DURATION_MS has already elapsed by the time we get
               here, so only delay the difference. */
            if (ADV_PERIOD_MS > ADV_EVENT_DURATION_MS) {
                vTaskDelay(pdMS_TO_TICKS(ADV_PERIOD_MS - ADV_EVENT_DURATION_MS));
            }
 
            start_advertising();
            break;
 
        default:
            break;
    }
    return 0;
}
 
static void start_advertising(void) {
    /* Local variables */
    int rc = 0;
    const char *name;
    struct ble_hs_adv_fields adv_fields = {0};
    struct ble_gap_adv_params adv_params = {0};
 
    /* Flags: BLE-only (no BR/EDR). Omit general/limited discoverable bits so
     * the ADV payload matches non-scannable beacon behavior below. Name and
     * other fields still allow passive scanners (e.g. nRF Connect) to see us. */
    adv_fields.flags = BLE_HS_ADV_F_BREDR_UNSUP;
 
    /* Set device name */
    name = ble_svc_gap_device_name();
    adv_fields.name = (uint8_t *)name;
    adv_fields.name_len = strlen(name);
    adv_fields.name_is_complete = 1;
 
    /* Set device tx power */
    adv_fields.tx_pwr_lvl = BLE_HS_ADV_TX_PWR_LVL_AUTO;
    adv_fields.tx_pwr_lvl_is_present = 1;
 
    /* Set device appearance */
    adv_fields.appearance = BLE_GAP_APPEARANCE_GENERIC_TAG;
    adv_fields.appearance_is_present = 1;
 
    /* Set device LE role */
    adv_fields.le_role = BLE_GAP_LE_ROLE_PERIPHERAL;
    adv_fields.le_role_is_present = 1;
 
    /* Set advertisement fields */
    rc = ble_gap_adv_set_fields(&adv_fields);
    if (rc != 0) {
        ESP_LOGE(TAG, "failed to set advertising data, error code: %d", rc);
        return;
    }
 
    /* Intentionally no ble_gap_adv_rsp_set_fields(): scan-response payload
     * (address/URI in the stock example) is unused once advertising is
     * ADV_NONCONN_IND. Leaving it programmed would only invite confusion. */
 
    /* Non-connectable + non-discoverable => ADV_NONCONN_IND in NimBLE
     * (see ble_gap_adv_type). Stock example used DISC_MODE_GEN, which with
     * CONN_MODE_NON yields ADV_SCAN_IND: TX then RX for SCAN_REQ, and a
     * SCAN_RSP TX if any active scanner answers. That stray TX made supply
     * rail captures jumpy in busy customer RF environments. */
    adv_params.conn_mode = BLE_GAP_CONN_MODE_NON;
    adv_params.disc_mode = BLE_GAP_DISC_MODE_NON;
 
    /* Toggle marker HIGH immediately before requesting the burst set */
    gpio_set_level(ADV_MARKER_GPIO, 1);
 
    /* Start a single short advertising event instead of BLE_HS_FOREVER.
       gap_event_handler will be called back on BLE_GAP_EVENT_ADV_COMPLETE
       once this event finishes, at which point it drops the marker and
       re-arms the next one. */
    rc = ble_gap_adv_start(own_addr_type, NULL, ADV_EVENT_DURATION_MS,
                            &adv_params, gap_event_handler, NULL);
    if (rc != 0) {
        ESP_LOGE(TAG, "failed to start advertising, error code: %d", rc);
        gpio_set_level(ADV_MARKER_GPIO, 0);
        return;
    }
}
 
/* Public functions */
void adv_init(void) {
    /* Local variables */
    int rc = 0;
    char addr_str[18] = {0};
 
    init_marker_gpio();
 
    /* Make sure we have proper BT identity address set */
    rc = ble_hs_util_ensure_addr(0);
    if (rc != 0) {
        ESP_LOGE(TAG, "device does not have any available bt address!");
        return;
    }
 
    /* Figure out BT address to use while advertising */
    rc = ble_hs_id_infer_auto(0, &own_addr_type);
    if (rc != 0) {
        ESP_LOGE(TAG, "failed to infer address type, error code: %d", rc);
        return;
    }
 
    /* Copy device address to addr_val */
    rc = ble_hs_id_copy_addr(own_addr_type, addr_val, NULL);
    if (rc != 0) {
        ESP_LOGE(TAG, "failed to copy device address, error code: %d", rc);
        return;
    }
    format_addr(addr_str, addr_val);
    ESP_LOGI(TAG, "device address: %s", addr_str);
 
    /* Start advertising. */
    start_advertising();
}
 
int gap_init(void) {
    /* Local variables */
    int rc = 0;
 
    /* Initialize GAP service */
    ble_svc_gap_init();
 
    /* Set GAP device name */
    rc = ble_svc_gap_device_name_set(DEVICE_NAME);
    if (rc != 0) {
        ESP_LOGE(TAG, "failed to set device name to %s, error code: %d",
                 DEVICE_NAME, rc);
        return rc;
    }
 
    /* Set GAP device appearance */
    rc = ble_svc_gap_device_appearance_set(BLE_GAP_APPEARANCE_GENERIC_TAG);
    if (rc != 0) {
        ESP_LOGE(TAG, "failed to set device appearance, error code: %d", rc);
        return rc;
    }
    return rc;
}