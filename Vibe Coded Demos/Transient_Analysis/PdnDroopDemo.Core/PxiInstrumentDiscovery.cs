using System;
using System.Collections.Generic;
using System.Text.RegularExpressions;
using NationalInstruments.SystemConfiguration;

namespace PdnDroopDemo
{
    /// <summary>
    /// Resource names for the single PXIe scope, waveform generator, and SMU
    /// expected on this station, plus the controller/chassis name used for
    /// TRIG_SMB and PXI_Trig routing.
    /// </summary>
    public sealed class DiscoveredPxiInstruments
    {
        public DiscoveredPxiInstruments(
            string scopeResourceName,
            string fgenResourceName,
            string smuResourceName,
            string triggerDeviceName)
        {
            ScopeResourceName = scopeResourceName;
            FgenResourceName = fgenResourceName;
            SmuResourceName = smuResourceName;
            TriggerDeviceName = triggerDeviceName;
        }

        /// <summary>MAX name accepted by NI-SCOPE (for example PXI1Slot2).</summary>
        public string ScopeResourceName { get; private set; }

        /// <summary>MAX name accepted by NI-FGEN (for example PXI1Slot3).</summary>
        public string FgenResourceName { get; private set; }

        /// <summary>MAX name for the SMU without a channel suffix (for example PXI1Slot4).</summary>
        public string SmuResourceName { get; private set; }

        /// <summary>Controller or chassis name for /&lt;name&gt;/TRIG_SMB routes.</summary>
        public string TriggerDeviceName { get; private set; }

        /// <summary>GPIO10 front-panel SMB terminal for the scope digital trigger.</summary>
        public string ScopeTriggerSource
        {
            get { return "/" + TriggerDeviceName + "/TRIG_SMB"; }
        }
    }

    /// <summary>
    /// Finds the present PXIe scope, arb, and SMU via NI System Configuration.
    /// Matches the brownout demo's Python <c>discover_pxi_instruments</c>: no
    /// hardcoded MAX aliases, exactly one of each instrument type.
    /// </summary>
    public static class PxiInstrumentDiscovery
    {
        // Same product-name families as Brownout_Threshold/brownout_voltage_sweep.py.
        private static readonly Regex ScopeProduct = new Regex(
            @"PXI[eE]?-51\d{2}|OSCILLOSCOPE|DIGITIZER",
            RegexOptions.IgnoreCase | RegexOptions.CultureInvariant);

        private static readonly Regex FgenProduct = new Regex(
            @"PXI[eE]?-54\d{2}|WAVEFORM GENERATOR|ARBITRARY",
            RegexOptions.IgnoreCase | RegexOptions.CultureInvariant);

        private static readonly Regex SmuProduct = new Regex(
            @"PXI[eE]?-41[3-6]\d|SOURCE MEASURE|\bSMU\b",
            RegexOptions.IgnoreCase | RegexOptions.CultureInvariant);

        private static readonly Regex ControllerProduct = new Regex(
            @"PXI[eE]?-88\d{2}|EMBEDDED CONTROLLER",
            RegexOptions.IgnoreCase | RegexOptions.CultureInvariant);

        private static readonly Regex ChassisProduct = new Regex(
            @"PXI[eE]?-10\d{2}",
            RegexOptions.IgnoreCase | RegexOptions.CultureInvariant);

        /// <summary>
        /// Enumerate present NI devices and return the single scope, arb, and SMU.
        /// Uses each device's MAX name (<see cref="HardwareResourceBase.UserAlias"/>),
        /// which is what NI-SCOPE / NI-FGEN / NI-DCPower sessions accept.
        /// </summary>
        public static DiscoveredPxiInstruments Discover()
        {
            List<string> scopes = new List<string>();
            List<string> fgens = new List<string>();
            List<string> smus = new List<string>();
            List<string> controllers = new List<string>();
            List<string> chassis = new List<string>();

            // Empty expert list: FindHardware with no expert filter is the
            // reliable path (nidcpower-focused expert queries miss SMUs).
            using (SystemConfiguration session = new SystemConfiguration("localhost"))
            {
                Filter filter = new Filter(session);
                filter.IsPresent = IsPresentType.Present;
                filter.IsNIProduct = true;
                filter.IsDevice = true;

                ResourceCollection resources = session.FindHardware(filter);
                foreach (HardwareResourceBase resource in resources)
                {
                    string product = TryGetProductName(resource);
                    if (product.IndexOf("PXI", StringComparison.OrdinalIgnoreCase) < 0)
                    {
                        continue;
                    }

                    string name = TryGetResourceName(resource);
                    if (string.IsNullOrEmpty(name))
                    {
                        continue;
                    }

                    if (ControllerProduct.IsMatch(product))
                    {
                        controllers.Add(name);
                    }
                    else if (ChassisProduct.IsMatch(product))
                    {
                        chassis.Add(name);
                    }
                    else if (ScopeProduct.IsMatch(product))
                    {
                        scopes.Add(name);
                    }
                    else if (FgenProduct.IsMatch(product))
                    {
                        fgens.Add(name);
                    }
                    else if (SmuProduct.IsMatch(product))
                    {
                        smus.Add(name);
                    }
                }
            }

            string scope = ExactlyOne("oscilloscope", scopes);
            string fgen = ExactlyOne("waveform generator", fgens);
            string smu = ExactlyOne("SMU", smus);

            string triggerDevice;
            if (controllers.Count > 0)
            {
                triggerDevice = controllers[0];
            }
            else if (chassis.Count > 0)
            {
                triggerDevice = chassis[0];
            }
            else
            {
                throw new InvalidOperationException(
                    "No PXI controller or chassis found for TRIG_SMB / PXI_Trig routing.");
            }

            return new DiscoveredPxiInstruments(scope, fgen, smu, triggerDevice);
        }

        private static string ExactlyOne(string role, List<string> found)
        {
            if (found.Count == 1)
            {
                return found[0];
            }
            if (found.Count == 0)
            {
                throw new InvalidOperationException("No PXIe " + role + " found in the system.");
            }
            throw new InvalidOperationException(
                "Expected exactly one PXIe " + role + ", found " + found.Count.ToString()
                + ": " + string.Join(", ", found.ToArray()));
        }

        private static string TryGetProductName(HardwareResourceBase resource)
        {
            try
            {
                HardwareResource hardware = resource as HardwareResource;
                if (hardware != null && !string.IsNullOrEmpty(hardware.ProductName))
                {
                    return hardware.ProductName;
                }
            }
            catch (SystemConfigurationException)
            {
            }

            return string.Empty;
        }

        /// <summary>
        /// Prefer the MAX alias (same value Python nisyscfg exposes as <c>name</c>).
        /// Fall back to the first expert user alias when the top-level alias is empty.
        /// </summary>
        private static string TryGetResourceName(HardwareResourceBase resource)
        {
            try
            {
                if (!string.IsNullOrEmpty(resource.UserAlias))
                {
                    return resource.UserAlias;
                }
            }
            catch (SystemConfigurationException)
            {
            }

            try
            {
                foreach (ExpertResourceInfo expert in resource.Experts)
                {
                    if (!string.IsNullOrEmpty(expert.UserAlias))
                    {
                        return expert.UserAlias;
                    }
                }
            }
            catch (SystemConfigurationException)
            {
            }

            return string.Empty;
        }
    }
}
