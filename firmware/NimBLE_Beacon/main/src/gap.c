/*
 * SPDX-FileCopyrightText: 2024 Espressif Systems (Shanghai) CO LTD
 *
 * SPDX-License-Identifier: Unlicense OR CC0-1.0
 *
 * MODIFIED: Forced non-scannable advertising (ADV_NONCONN_IND) so the DUT never
 * opens a post-ADV RX window or transmits SCAN_RSP. In busy RF environments,
 * active scanners were eliciting unpredictable scan responses that made rail
 * voltage and current captures jumpy; quiet lab benches rarely saw that activity.
 */
/* Includes */
#include "gap.h"
#include "common.h"

/* Private function declarations */
inline static void format_addr(char *addr_str, uint8_t addr[]);
static void start_advertising(void);

/* Private variables */
static uint8_t own_addr_type;
static uint8_t addr_val[6] = {0};

/* Private functions */
inline static void format_addr(char *addr_str, uint8_t addr[]) {
    sprintf(addr_str, "%02X:%02X:%02X:%02X:%02X:%02X", addr[0], addr[1],
            addr[2], addr[3], addr[4], addr[5]);
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

    /* Start advertising */
    rc = ble_gap_adv_start(own_addr_type, NULL, BLE_HS_FOREVER, &adv_params,
                           NULL, NULL);
    if (rc != 0) {
        ESP_LOGE(TAG, "failed to start advertising, error code: %d", rc);
        return;
    }
    ESP_LOGI(TAG, "advertising started!");
}

/* Public functions */
void adv_init(void) {
    /* Local variables */
    int rc = 0;
    char addr_str[18] = {0};

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
