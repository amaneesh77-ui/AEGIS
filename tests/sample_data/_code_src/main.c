// Firmware entry point
#include "uart_driver.h"
#include "i2c_driver.h"

int main(void) {
    uart_init(115200);      // UART comms
    i2c_init();             // I2C sensor bus
    bootloader_check_ota(); // OTA update path
    return 0;
}
