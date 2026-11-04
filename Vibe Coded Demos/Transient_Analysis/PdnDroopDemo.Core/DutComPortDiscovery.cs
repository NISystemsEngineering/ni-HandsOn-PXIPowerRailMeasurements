using System;
using System.Collections.Generic;
using System.IO.Ports;
using System.Management;
using System.Text.RegularExpressions;

namespace PdnDroopDemo
{
    /// <summary>
    /// One serial port the GUI can offer for the ESP32-C6 DevKit UART.
    /// </summary>
    public class DutComPortInfo
    {
        /// <summary>Windows device name, for example COM10.</summary>
        public string Label { get; set; }

        /// <summary>Friendly description from the OS (manufacturer / PnP name).</summary>
        public string Description { get; set; }

        public override string ToString()
        {
            return Label;
        }
    }

    /// <summary>
    /// Lists COM ports the same way the brownout Python GUI does: prefer Silicon
    /// Labs CP210x, never favor the built-in "Communications Port".
    /// </summary>
    public static class DutComPortDiscovery
    {
        private static readonly Regex ComDevice = new Regex(@"^COM(\d+)$", RegexOptions.IgnoreCase);
        private static readonly Regex ComInName = new Regex(@"\((COM\d+)\)", RegexOptions.IgnoreCase);
        private static readonly Regex SilabsUart = new Regex(@"Silicon Labs|CP210", RegexOptions.IgnoreCase);
        private static readonly Regex BuiltinCom = new Regex(
            @"Communications Port|Standard port types",
            RegexOptions.IgnoreCase);

        /// <summary>Fallback when nothing is plugged in. Matches this station's CP210x.</summary>
        public const string DefaultComLabel = "COM10";

        /// <summary>
        /// Serial ports as (COM label, description), Silicon Labs first, built-in last.
        /// </summary>
        public static List<DutComPortInfo> ListComPorts()
        {
            Dictionary<string, string> byLabel = new Dictionary<string, string>(
                StringComparer.OrdinalIgnoreCase);

            try
            {
                string[] names = SerialPort.GetPortNames();
                for (int index = 0; index < names.Length; index++)
                {
                    Match match = ComDevice.Match(names[index] ?? "");
                    if (!match.Success)
                    {
                        continue;
                    }

                    string label = "COM" + match.Groups[1].Value;
                    if (!byLabel.ContainsKey(label))
                    {
                        byLabel[label] = label;
                    }
                }
            }
            catch
            {
                // Leave the dictionary empty; WMI may still find ports.
            }

            try
            {
                using (ManagementObjectSearcher searcher = new ManagementObjectSearcher(
                    "SELECT Name, Caption, Description FROM Win32_PnPEntity WHERE Name LIKE '%(COM%'"))
                {
                    foreach (ManagementObject device in searcher.Get())
                    {
                        string name = Convert.ToString(device["Name"]) ?? "";
                        Match match = ComInName.Match(name);
                        if (!match.Success)
                        {
                            continue;
                        }

                        string label = match.Groups[1].Value.ToUpperInvariant();
                        string description =
                            Convert.ToString(device["Caption"])
                            ?? Convert.ToString(device["Description"])
                            ?? name;
                        byLabel[label] = description;
                    }
                }
            }
            catch
            {
                // SerialPort.GetPortNames results alone are still usable.
            }

            List<DutComPortInfo> ports = new List<DutComPortInfo>();
            foreach (KeyValuePair<string, string> pair in byLabel)
            {
                DutComPortInfo info = new DutComPortInfo();
                info.Label = pair.Key.ToUpperInvariant();
                info.Description = pair.Value;
                ports.Add(info);
            }

            ports.Sort(ComparePorts);
            return ports;
        }

        /// <summary>
        /// Same preference order as brownout_voltage_gui.preferred_com_label:
        /// Silicon Labs / CP210x, then any non-built-in, then first listed.
        /// </summary>
        public static string PreferredComLabel(IList<DutComPortInfo> ports)
        {
            if (ports == null || ports.Count == 0)
            {
                return DefaultComLabel;
            }

            for (int index = 0; index < ports.Count; index++)
            {
                if (SilabsUart.IsMatch(ports[index].Description ?? ""))
                {
                    return ports[index].Label;
                }
            }

            for (int index = 0; index < ports.Count; index++)
            {
                if (!BuiltinCom.IsMatch(ports[index].Description ?? ""))
                {
                    return ports[index].Label;
                }
            }

            return ports[0].Label;
        }

        private static int ComparePorts(DutComPortInfo left, DutComPortInfo right)
        {
            int leftRank = Rank(left.Description);
            int rightRank = Rank(right.Description);
            if (leftRank != rightRank)
            {
                return leftRank.CompareTo(rightRank);
            }

            return PortNumber(left.Label).CompareTo(PortNumber(right.Label));
        }

        private static int Rank(string description)
        {
            if (SilabsUart.IsMatch(description ?? ""))
            {
                return 0;
            }
            if (BuiltinCom.IsMatch(description ?? ""))
            {
                return 2;
            }
            return 1;
        }

        private static int PortNumber(string label)
        {
            Match match = ComDevice.Match(label ?? "");
            if (!match.Success)
            {
                return int.MaxValue;
            }
            return int.Parse(match.Groups[1].Value);
        }
    }
}
