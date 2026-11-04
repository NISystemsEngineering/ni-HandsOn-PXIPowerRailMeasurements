using System;
using System.IO.Ports;
using System.Threading;

namespace PdnDroopDemo
{
    /// <summary>
    /// Reboots the ESP32-C6 DevKitC-1 through its auto-reset circuit (RTS → EN,
    /// DTR → boot strap). Same sequence the brownout Python sweep uses.
    /// </summary>
    public static class DutReset
    {
        /// <summary>
        /// Pulse DTR/RTS on comPortLabel (for example COM10), then wait for
        /// advertising to come back. Baud rate only matters for opening the port;
        /// the warning-only firmware is not spoken to here.
        /// </summary>
        public static void ResetAndWaitForAdvertising(string comPortLabel, double waitSeconds)
        {
            if (string.IsNullOrEmpty(comPortLabel))
            {
                throw new ArgumentException("A DUT COM port is required for reset.");
            }

            using (SerialPort port = new SerialPort(comPortLabel, 115200))
            {
                port.Handshake = Handshake.None;
                port.DtrEnable = false;
                port.RtsEnable = false;

                try
                {
                    port.Open();
                }
                catch (Exception ex)
                {
                    throw new InvalidOperationException(
                        "Could not open " + comPortLabel + " for the DevKit reset. "
                        + "Pick the Silicon Labs CP210x port. " + ex.Message,
                        ex);
                }

                // esptool classic / brownout_voltage_sweep._reset_dut:
                // (False, False), (True, True), (False, True) for 100 ms, (False, False).
                SetDtrRts(port, false, false);
                SetDtrRts(port, true, true);
                SetDtrRts(port, false, true);
                Thread.Sleep(100);
                SetDtrRts(port, false, false);
            }

            if (waitSeconds > 0)
            {
                Thread.Sleep((int)(waitSeconds * 1000.0));
            }
        }

        private static void SetDtrRts(SerialPort port, bool dtr, bool rts)
        {
            port.DtrEnable = dtr;
            port.RtsEnable = rts;
        }
    }
}
