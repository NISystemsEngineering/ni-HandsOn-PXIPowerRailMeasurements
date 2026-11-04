using System;
using System.Threading;
using NationalInstruments;
using NationalInstruments.ModularInstruments.NIDCPower;
using NationalInstruments.ModularInstruments.NIScope;

namespace PdnDroopDemo
{
    /// <summary>
    /// Every number a presenter can point at and change. Leave instrument resource
    /// names empty to discover the single present PXIe scope, arb, and SMU at run
    /// time (same approach as the brownout Python sweep).
    /// </summary>
    public class DroopMeasurementSettings
    {
        /// <summary>How many advertising bursts to capture. Twenty-five finishes in a few seconds.</summary>
        public int TrialCount { get; set; } = 25;

        /// <summary>Fixed rail voltage. 3.50 V is above the 3.27 V brownout detector, so the DUT keeps advertising.</summary>
        public double RailVoltageVolts { get; set; } = 3.50;

        /// <summary>SMU current limit in amps (1 A). A healthy DUT draws about 40 to 50 mA; this leaves room for the radio peak and SourceAdapt.</summary>
        public double CurrentLimitAmps { get; set; } = 1.0;

        /// <summary>Range for that current limit. The NI-DCPower single-point example sets the range separately, and it must be at least the limit.</summary>
        public double CurrentLimitRangeAmps { get; set; } = 1.0;

        /// <summary>Voltage range for the 3.5 V rail. 6 V is the range in the NI-DCPower single-point example and in the brownout demo.</summary>
        public double VoltageLevelRangeVolts { get; set; } = 6.0;

        /// <summary>A trial passes when the droop is at or under this many millivolts. Training budget, not a measured result.</summary>
        public double DroopSpecLimitMillivolts { get; set; } = 140.0;

        /// <summary>
        /// Absolute millivolt band around the quiet baseline used only when
        /// RecoveryPercentOfPeakDroop is 0. Prefer percent-of-droop recovery for
        /// AC-coupled captures (a few mV of AC pedestal would fail a tight band).
        /// </summary>
        public double SettlingBandMillivolts { get; set; } = 20.0;

        /// <summary>
        /// Post-burst recovery succeeds when the rail has climbed this fraction of
        /// the peak droop (0.90 = 10% of the dip still remaining). 0 disables
        /// percent recovery and uses SettlingBandMillivolts instead.
        /// </summary>
        public double RecoveryPercentOfPeakDroop { get; set; } = 0.90;

        /// <summary>
        /// After crossing the recovery threshold, the rail must stay recovered this
        /// long. Keep short: GPIO10 leads the RF current by milliseconds, so the
        /// record has limited post-burst samples unless RecordLength is increased.
        /// </summary>
        public double SettlingHoldTimeMicroseconds { get; set; } = 10.0;

        /// <summary>
        /// Drop this far below the pre-trigger baseline to start an ADV_IND packet dip.
        /// Exit is halfway back toward the baseline.
        /// </summary>
        public double PacketDetectMillivolts { get; set; } = 30.0;

        /// <summary>Ignore detected dips shorter than this (noise spikes, not TX current).</summary>
        public double MinimumPacketWidthMicroseconds { get; set; } = 20.0;

        /// <summary>
        /// Legacy BLE advertising sends one ADV_IND on each of channels 37, 38, and 39.
        /// Firmware that skips SCAN_REQUEST still does that; the three dips are just closer.
        /// </summary>
        public int ExpectedAdvertisingPacketCount { get; set; } = 3;

        /// <summary>
        /// Minimum samples in the scope record. GPIO10 fires ~2.5 ms before the
        /// ADV_IND current dips on this firmware, so 20 k samples at 2 MS/s leaves
        /// enough post-burst room for recovery timing (~9.5 ms after a 5% ref).
        /// </summary>
        public int RecordLengthSamples { get; set; } = 20000;

        /// <summary>Minimum sample rate. 2 MS/s is the rate the brownout demo uses on this scope.</summary>
        public double MinimumSampleRateSamplesPerSecond { get; set; } = 2.0e6;

        /// <summary>
        /// Full-scale vertical window, in volts peak-to-peak. With AC coupling and
        /// offset 0 this is centered on the quiet baseline so a ~100 mV droop fills
        /// a useful fraction of the screen (same 1 V range as InstrumentStudio).
        /// </summary>
        public double VerticalRangeVolts { get; set; } = 1.0;

        /// <summary>
        /// Channel bandwidth limit in hertz. 20 MHz is the lowest limit on the
        /// PXIe-5164; 0 would mean full bandwidth. Limiting rejects RF/switching
        /// junk that is not part of the advertising current step.
        /// </summary>
        public double ScopeBandwidthHertz { get; set; } = 20.0e6;

        /// <summary>
        /// AC coupling strips the 3.4 V rail so the plot and digitizer window sit
        /// around 0 V and the droop is readable. Droop depth is still measured
        /// against the pre-trigger AC baseline. Set false for DC with offset = rail.
        /// </summary>
        public bool UseAcCoupling { get; set; } = true;

        /// <summary>
        /// Percent of the record kept before the trigger. Keep this small so most
        /// of the record covers the late ADV_IND burst and the post-burst recovery.
        /// </summary>
        public double ReferencePositionPercent { get; set; } = 5.0;

        /// <summary>How long to wait for the next GPIO10 edge before calling the DUT idle. Advertising is well under a second.</summary>
        public double ScopeTriggerTimeoutSeconds { get; set; } = 2.0;

        /// <summary>How long the rail sits at voltage before the first arm, so the scope's pre-trigger is not the SMU ramp.</summary>
        public double RailSettleTimeSeconds { get; set; } = 0.2;

        /// <summary>Bins in each histogram. The edges are the min and max of the trials just taken.</summary>
        public int HistogramBinCount { get; set; } = 8;

        /// <summary>
        /// DevKit UART, for example COM10. Used for the DTR/RTS reset that brings
        /// advertising back. Empty means discover and prefer Silicon Labs CP210x
        /// (same rule as the brownout GUI).
        /// </summary>
        public string DutComPort { get; set; } = DutComPortDiscovery.DefaultComLabel;

        /// <summary>
        /// After the DTR/RTS pulse, wait this long for BLE advertising before the
        /// first scope arm. Matches the brownout sweep's post-reset pause.
        /// </summary>
        public double DutResetAdvertiseWaitSeconds { get; set; } = 1.5;

        /// <summary>
        /// When true, pulse the DevKit reset once after the SMU is sourcing and
        /// before the first trial. Needed when the chip is idle and GPIO10 never fires.
        /// </summary>
        public bool ResetDutBeforeTrials { get; set; } = true;

        /// <summary>
        /// SMU MAX name without a channel suffix. Empty means discover the single
        /// present PXIe SMU (for example PXI1Slot4).
        /// </summary>
        public string SmuResourceName { get; set; }

        /// <summary>Channel on that SMU. The session is opened as SmuResourceName/SmuChannelName.</summary>
        public string SmuChannelName { get; set; } = "0";

        /// <summary>
        /// Scope MAX name. Empty means discover the single present PXIe digitizer
        /// (for example PXI1Slot2).
        /// </summary>
        public string ScopeResourceName { get; set; }

        /// <summary>
        /// Waveform-generator MAX name. This demo does not open NI-FGEN; the name
        /// is still discovered so the station layout (one scope, one arb, one SMU)
        /// is validated. Empty means discover.
        /// </summary>
        public string FgenResourceName { get; set; }

        /// <summary>Scope channel on the rail. Channel 1 is the shunt, and this demo does not use it.</summary>
        public string ScopeChannelName { get; set; } = "0";

        /// <summary>
        /// GPIO10 arrives on the chassis front-panel SMB. Empty means
        /// /&lt;discovered controller&gt;/TRIG_SMB.
        /// </summary>
        public string ScopeTriggerSource { get; set; }

        /// <summary>The scope copies that trigger onto the backplane. The brownout demo's arb listens here; this demo exports the same line and listens to nothing.</summary>
        public string ScopeReferenceTriggerExport { get; set; } = "PXI_Trig0";

        /// <summary>
        /// Fill any empty instrument / trigger fields from NI System Configuration.
        /// Requires exactly one present PXIe scope, waveform generator, and SMU.
        /// </summary>
        public DiscoveredPxiInstruments ResolveInstrumentResources()
        {
            bool needScope = string.IsNullOrEmpty(ScopeResourceName);
            bool needFgen = string.IsNullOrEmpty(FgenResourceName);
            bool needSmu = string.IsNullOrEmpty(SmuResourceName);
            bool needTrigger = string.IsNullOrEmpty(ScopeTriggerSource);

            if (!needScope && !needFgen && !needSmu && !needTrigger)
            {
                return null;
            }

            DiscoveredPxiInstruments discovered = PxiInstrumentDiscovery.Discover();
            if (needScope)
            {
                ScopeResourceName = discovered.ScopeResourceName;
            }
            if (needFgen)
            {
                FgenResourceName = discovered.FgenResourceName;
            }
            if (needSmu)
            {
                SmuResourceName = discovered.SmuResourceName;
            }
            if (needTrigger)
            {
                ScopeTriggerSource = discovered.ScopeTriggerSource;
            }
            return discovered;
        }
    }

    /// <summary>
    /// Hold the ESP32-C6 rail at one healthy voltage and measure the natural droop
    /// each time the radio keys up. No ripple injection, no arb. The DUT COM port
    /// is only used for a one-shot DTR/RTS reset before the trials.
    /// Construct it, call RunTrials, and dispose it. TestStand can do the same.
    /// </summary>
    public class DroopMeasurement : IDisposable
    {
        // The acquisition is already complete before the fetch, so this only
        // covers the DMA. The wait for GPIO10 uses ScopeTriggerTimeoutSeconds.
        private const double FetchTimeoutSeconds = 5.0;
        private const double SourceCompleteTimeoutSeconds = 5.0;
        private const int PollIntervalMilliseconds = 5;

        // The part on this station is used up to 3.6 V. A typo above that is a
        // broken setting, not a measurement.
        private const double MaximumRailVoltageVolts = 3.6;

        private readonly DroopMeasurementSettings _settings;
        private NIDCPower _smu;
        private string _smuChannel;
        private NIScope _scope;
        private ScopeChannel _scopeChannel;

        private int _recordLengthSamples;
        private int _preTriggerSampleCount;
        private double _sampleIntervalSeconds;

        private volatile bool _stopRequested;

        /// <summary>Set this to stop between trials. The trial already in flight finishes.</summary>
        public bool StopRequested
        {
            get { return _stopRequested; }
            set { _stopRequested = value; }
        }

        /// <summary>The settings this run will use. Change them before RunTrials.</summary>
        public DroopMeasurementSettings Settings
        {
            get { return _settings; }
        }

        public DroopMeasurement(DroopMeasurementSettings settings)
        {
            if (settings == null)
            {
                throw new ArgumentNullException("settings");
            }
            _settings = settings;
        }

        /// <summary>
        /// Source the rail, capture TrialCount bursts, and return the summary.
        /// reportTrial may be null. When it is not, it is called after every
        /// burst, on this same thread, before the next arm.
        /// reportPhase may be null. SettingUp covers SMU/scope/DUT reset/precheck;
        /// Running starts when the first measurement arm begins.
        /// </summary>
        public DroopStatistics RunTrials(
            Action<TrialResult> reportTrial,
            Action<MeasurementPhase> reportPhase)
        {
            ReportPhase(reportPhase, MeasurementPhase.SettingUp);

            // Discover MAX names when the caller left resource fields empty.
            _settings.ResolveInstrumentResources();
            ResolveDutComPort();
            CheckSettings();

            bool runFinished = false;
            try
            {
                // =============================================================================
                // Instrument setup
                // =============================================================================
                OpenSmu();
                OpenScope();

                if (_settings.ResetDutBeforeTrials)
                {
                    DutReset.ResetAndWaitForAdvertising(
                        _settings.DutComPort,
                        _settings.DutResetAdvertiseWaitSeconds);
                }

                // Prove GPIO10 is toggling before the trial loop. Same idea as the
                // brownout health check: a timed-out scope arm means the DUT is idle.
                ConfirmAdvertisingPrecheck();

                ReportPhase(reportPhase, MeasurementPhase.Running);

                TrialResult[] trials = new TrialResult[_settings.TrialCount];
                int completedCount = 0;

                for (int trialIndex = 0; trialIndex < _settings.TrialCount; trialIndex++)
                {
                    if (StopRequested)
                    {
                        break;
                    }

                    // A timeout or a driver error fails the run. It is not stored
                    // as a trial with no data.
                    try
                    {
                        // =============================================================================
                        // Single-trial capture
                        // =============================================================================
                        trials[trialIndex] = CaptureOneTrial(trialIndex + 1);
                    }
                    catch (Exception ex)
                    {
                        throw new InvalidOperationException(
                            "Trial " + (trialIndex + 1).ToString() + " of " + _settings.TrialCount.ToString()
                            + " failed. " + ex.Message,
                            ex);
                    }

                    completedCount = completedCount + 1;
                    if (reportTrial != null)
                    {
                        reportTrial(trials[trialIndex]);
                    }
                }

                // =============================================================================
                // Statistics
                // =============================================================================
                TrialResult[] completed = new TrialResult[completedCount];
                for (int trialIndex = 0; trialIndex < completedCount; trialIndex++)
                {
                    completed[trialIndex] = trials[trialIndex];
                }

                runFinished = true;
                return DroopStatistics.FromTrials(completed, _settings);
            }
            finally
            {
                // =============================================================================
                // Teardown
                // =============================================================================
                // Always drop the output and release both sessions, including
                // when a trial threw. A close error must not hide that trial error.
                CloseInstruments(runFinished);
            }
        }

        public void Dispose()
        {
            CloseInstruments(false);
        }

        private static void ReportPhase(Action<MeasurementPhase> reportPhase, MeasurementPhase phase)
        {
            if (reportPhase != null)
            {
                reportPhase(phase);
            }
        }

        private void CheckSettings()
        {
            if (_settings.TrialCount < 1)
            {
                throw new ArgumentException("TrialCount must be at least 1.");
            }
            if (_settings.RailVoltageVolts <= 0 || _settings.RailVoltageVolts > MaximumRailVoltageVolts)
            {
                throw new ArgumentException(
                    "RailVoltageVolts must be between 0 and " + MaximumRailVoltageVolts.ToString("0.0")
                    + " V. This DUT is used up to 3.6 V.");
            }
            if (_settings.CurrentLimitAmps <= 0)
            {
                throw new ArgumentException("CurrentLimitAmps must be positive.");
            }
            if (_settings.RecordLengthSamples < 100)
            {
                throw new ArgumentException("RecordLengthSamples must be at least 100.");
            }
            if (_settings.MinimumSampleRateSamplesPerSecond <= 0)
            {
                throw new ArgumentException("MinimumSampleRateSamplesPerSecond must be positive.");
            }
            if (_settings.VerticalRangeVolts <= 0)
            {
                throw new ArgumentException("VerticalRangeVolts must be positive.");
            }
            if (_settings.ReferencePositionPercent < 1 || _settings.ReferencePositionPercent > 50)
            {
                throw new ArgumentException(
                    "ReferencePositionPercent must be from 1 to 50 so the record has a pre-trigger rail and room after the trigger.");
            }
            if (_settings.ScopeTriggerTimeoutSeconds <= 0)
            {
                throw new ArgumentException("ScopeTriggerTimeoutSeconds must be positive.");
            }
            if (_settings.SettlingBandMillivolts <= 0)
            {
                throw new ArgumentException("SettlingBandMillivolts must be positive.");
            }
            if (_settings.RecoveryPercentOfPeakDroop < 0 || _settings.RecoveryPercentOfPeakDroop >= 1.0)
            {
                throw new ArgumentException(
                    "RecoveryPercentOfPeakDroop must be 0 (use absolute band) or in (0, 1).");
            }
            if (_settings.SettlingHoldTimeMicroseconds < 0)
            {
                throw new ArgumentException("SettlingHoldTimeMicroseconds cannot be negative.");
            }
            if (_settings.PacketDetectMillivolts <= 0)
            {
                throw new ArgumentException("PacketDetectMillivolts must be positive.");
            }
            if (_settings.MinimumPacketWidthMicroseconds < 0)
            {
                throw new ArgumentException("MinimumPacketWidthMicroseconds cannot be negative.");
            }
            if (_settings.ExpectedAdvertisingPacketCount < 1)
            {
                throw new ArgumentException("ExpectedAdvertisingPacketCount must be at least 1.");
            }
            if (_settings.ScopeBandwidthHertz < 0)
            {
                throw new ArgumentException("ScopeBandwidthHertz cannot be negative (0 means full bandwidth).");
            }
            if (_settings.HistogramBinCount < 1)
            {
                throw new ArgumentException("HistogramBinCount must be at least 1.");
            }
            if (string.IsNullOrEmpty(_settings.SmuResourceName) || string.IsNullOrEmpty(_settings.ScopeResourceName))
            {
                throw new ArgumentException("SMU and scope resource names are required.");
            }
            if (_settings.ResetDutBeforeTrials && string.IsNullOrEmpty(_settings.DutComPort))
            {
                throw new ArgumentException(
                    "DutComPort is required when ResetDutBeforeTrials is true (for example COM10).");
            }
            if (_settings.DutResetAdvertiseWaitSeconds < 0)
            {
                throw new ArgumentException("DutResetAdvertiseWaitSeconds cannot be negative.");
            }
        }

        private void ResolveDutComPort()
        {
            if (!string.IsNullOrEmpty(_settings.DutComPort))
            {
                return;
            }

            System.Collections.Generic.List<DutComPortInfo> ports = DutComPortDiscovery.ListComPorts();
            _settings.DutComPort = DutComPortDiscovery.PreferredComLabel(ports);
        }

        private void OpenSmu()
        {
            try
            {
                // Same open as the NI-DCPower "Source DC Voltage" example:
                // "<smu>/0", a reset flag, and an empty option string.
                _smuChannel = _settings.SmuResourceName + "/" + _settings.SmuChannelName;
                _smu = new NIDCPower(_smuChannel, true, "");

                // Source mode is a session setting. Voltage and current are set
                // on the fully qualified channel, "<smu>/0", not on "0" alone.
                _smu.Source.Mode = DCPowerSourceMode.SinglePoint;
                DCPowerOutput output = _smu.Outputs[_smuChannel];
                output.Source.Output.Function = DCPowerSourceOutputFunction.DCVoltage;

                // Remote sense uses the sense leads at the rail, same wiring as
                // the brownout demo, so the voltage at the header is the setpoint
                // rather than the voltage after the force-lead drop.
                output.Measurement.Sense = DCPowerMeasurementSense.Remote;

                // Same SourceAdapt as Brownout_Threshold / InstrumentStudio Fast
                // preset with Voltage GBW set to 100 kHz. CUSTOM is required for
                // these attributes to apply.
                output.Source.TransientResponse = DCPowerSourceTransientResponse.Custom;
                output.Source.CustomTransientResponse.Current.GainBandwidth = 200e3;
                output.Source.CustomTransientResponse.Current.CompensationFrequency = 40.0129e3;
                output.Source.CustomTransientResponse.Current.PoleZeroRatio = 0.59996;
                output.Source.CustomTransientResponse.Voltage.GainBandwidth = 100e3;
                output.Source.CustomTransientResponse.Voltage.CompensationFrequency = 200.023e3;
                output.Source.CustomTransientResponse.Voltage.PoleZeroRatio = 0.29996;

                output.Source.Voltage.VoltageLevelRange = _settings.VoltageLevelRangeVolts;
                output.Source.Voltage.CurrentLimitRange = _settings.CurrentLimitRangeAmps;
                output.Source.Voltage.VoltageLevel = _settings.RailVoltageVolts;
                output.Source.Voltage.CurrentLimit = _settings.CurrentLimitAmps;
                output.Source.Voltage.CurrentLimitHigh = _settings.CurrentLimitAmps;
                output.Source.SourceDelay = new PrecisionTimeSpan(_settings.RailSettleTimeSeconds);

                _smu.Control.Initiate();
                _smu.Events.SourceCompleteEvent.WaitForEvent(new PrecisionTimeSpan(SourceCompleteTimeoutSeconds));
            }
            catch (Exception ex)
            {
                throw new InvalidOperationException(
                    "Could not source " + _settings.RailVoltageVolts.ToString("0.00")
                    + " V from " + _settings.SmuResourceName + ". " + ex.Message,
                    ex);
            }
        }

        private void OpenScope()
        {
            try
            {
                _scope = new NIScope(_settings.ScopeResourceName, false, true);
                _scopeChannel = _scope.Channels[_settings.ScopeChannelName];

                // AC coupling (default): strip the 3.4 V rail so the 1 V window
                // sits on the quiet baseline and the advertising droop is readable
                // without a huge offset. Droop depth still comes from the
                // pre-trigger mean of the same record. DC + rail offset remains
                // available via UseAcCoupling = false.
                ScopeVerticalCoupling coupling = _settings.UseAcCoupling
                    ? ScopeVerticalCoupling.AC
                    : ScopeVerticalCoupling.DC;
                double verticalOffsetVolts = _settings.UseAcCoupling
                    ? 0.0
                    : _settings.RailVoltageVolts;
                _scopeChannel.Configure(
                    _settings.VerticalRangeVolts,
                    verticalOffsetVolts,
                    coupling,
                    1.0,
                    true);

                // 1 MΩ so the scope does not load the rail. Bandwidth is the
                // lowest limit on the PXIe-5164 (20 MHz) unless the setting is 0
                // (full bandwidth).
                _scopeChannel.ConfigureCharacteristics(1.0e6, _settings.ScopeBandwidthHertz);

                _scope.Timing.ConfigureTiming(
                    _settings.MinimumSampleRateSamplesPerSecond,
                    _settings.RecordLengthSamples,
                    _settings.ReferencePositionPercent,
                    1,
                    true);

                // Read back what the digitizer actually armed. ConfigureTiming
                // treats the rate and the length as minimums.
                _recordLengthSamples = (int)_scope.Acquisition.RecordLength;
                double actualSampleRate = _scope.Acquisition.SampleRate;
                if (actualSampleRate <= 0)
                {
                    throw new InvalidOperationException("The scope reported a sample rate of zero.");
                }
                _sampleIntervalSeconds = 1.0 / actualSampleRate;

                double actualReferencePositionPercent = _scope.Trigger.ReferenceTrigger.ReferencePosition;
                _preTriggerSampleCount = (int)Math.Round(
                    _recordLengthSamples * actualReferencePositionPercent / 100.0);
                if (_preTriggerSampleCount < 1 || _preTriggerSampleCount >= _recordLengthSamples)
                {
                    throw new InvalidOperationException(
                        "The scope's reference position did not leave both a pre-trigger rail and samples after the trigger.");
                }

                // Rising edge from GPIO10, no extra delay. A delay of a few
                // milliseconds, which InstrumentStudio has left on this scope,
                // would slide the record past the advertising current pulse.
                ScopeTriggerSource triggerSource = _settings.ScopeTriggerSource;
                _scope.Trigger.ConfigureTriggerDigital(
                    triggerSource,
                    ScopeTriggerSlope.Positive,
                    PrecisionTimeSpan.Zero,
                    PrecisionTimeSpan.Zero);
                _scope.Trigger.Modifier = ScopeTriggerModifier.None;

                // Drive PXI_Trig0 from the scope, the same export the brownout
                // demo uses so the arb can burst. Nothing listens this time.
                // A leftover DAQmx route from TRIG_SMB onto PXI_Trig0 will fight
                // this export; the brownout setup clears that route.
                _scope.ExportedSignals.ReferenceTriggerOutputTerminal = _settings.ScopeReferenceTriggerExport;
            }
            catch (Exception ex)
            {
                throw new InvalidOperationException(
                    "Could not arm " + _settings.ScopeResourceName + " on " + _settings.ScopeTriggerSource
                    + ". " + ex.Message,
                    ex);
            }
        }

        /// <summary>
        /// Arm the scope once and require a GPIO10 edge. On timeout, reset the DUT
        /// once more and try again. Fails the run before any trial is recorded.
        /// </summary>
        private void ConfirmAdvertisingPrecheck()
        {
            if (TryCaptureAdvertisingTrigger())
            {
                return;
            }

            if (_settings.ResetDutBeforeTrials && !string.IsNullOrEmpty(_settings.DutComPort))
            {
                DutReset.ResetAndWaitForAdvertising(
                    _settings.DutComPort,
                    _settings.DutResetAdvertiseWaitSeconds);
                if (TryCaptureAdvertisingTrigger())
                {
                    return;
                }
            }

            throw new TimeoutException(
                "Advertising precheck failed: no GPIO10 rising edge within "
                + _settings.ScopeTriggerTimeoutSeconds.ToString("0.0")
                + " s at " + _settings.RailVoltageVolts.ToString("0.00")
                + " V / " + (_settings.CurrentLimitAmps * 1000.0).ToString("0")
                + " mA on " + _settings.DutComPort
                + ". Check firmware, TRIG_SMB wiring, and the Silicon Labs COM port.");
        }

        /// <summary>
        /// One scope arm for the advertising digital trigger. Returns false on
        /// timeout (after abort). Throws on driver errors other than timeout.
        /// </summary>
        private bool TryCaptureAdvertisingTrigger()
        {
            _scope.Measurement.Initiate();

            DateTime armTime = DateTime.UtcNow;
            ScopeAcquisitionStatus status = _scope.Measurement.Status();
            while (status != ScopeAcquisitionStatus.Complete)
            {
                if (StopRequested)
                {
                    _scope.Measurement.Abort();
                    throw new OperationCanceledException("Stop requested during advertising precheck.");
                }

                double elapsedSeconds = (DateTime.UtcNow - armTime).TotalSeconds;
                if (elapsedSeconds > _settings.ScopeTriggerTimeoutSeconds)
                {
                    _scope.Measurement.Abort();
                    return false;
                }

                Thread.Sleep(PollIntervalMilliseconds);
                status = _scope.Measurement.Status();
            }

            // Fetch so the next Initiate starts clean; samples are not analyzed.
            AnalogWaveformCollection<double> waveforms = _scopeChannel.Measurement.FetchDouble(
                PrecisionTimeSpan.FromSeconds(FetchTimeoutSeconds),
                _recordLengthSamples,
                null);
            if (waveforms == null || waveforms.Count < 1)
            {
                throw new InvalidOperationException(
                    "Advertising precheck: the scope completed but returned no waveform.");
            }

            return true;
        }

        private TrialResult CaptureOneTrial(int trialNumber)
        {
            _scope.Measurement.Initiate();

            DateTime armTime = DateTime.UtcNow;
            ScopeAcquisitionStatus status = _scope.Measurement.Status();
            while (status != ScopeAcquisitionStatus.Complete)
            {
                double elapsedSeconds = (DateTime.UtcNow - armTime).TotalSeconds;
                if (elapsedSeconds > _settings.ScopeTriggerTimeoutSeconds)
                {
                    _scope.Measurement.Abort();
                    throw new TimeoutException(
                        "No GPIO10 rising edge within " + _settings.ScopeTriggerTimeoutSeconds.ToString("0.0")
                        + " s. The DUT is probably not advertising. A reset with the rail at "
                        + _settings.RailVoltageVolts.ToString("0.00") + " V brings it back.");
                }

                Thread.Sleep(PollIntervalMilliseconds);
                status = _scope.Measurement.Status();
            }

            // null asks the driver to allocate the waveform. FetchDouble returns
            // the samples already scaled into volts.
            AnalogWaveformCollection<double> waveforms = _scopeChannel.Measurement.FetchDouble(
                PrecisionTimeSpan.FromSeconds(FetchTimeoutSeconds),
                _recordLengthSamples,
                null);
            if (waveforms == null || waveforms.Count < 1)
            {
                throw new InvalidOperationException("The scope completed but returned no waveform.");
            }

            AnalogWaveform<double> waveform = waveforms[0];
            double[] voltageSamples = waveform.GetRawData();
            if (voltageSamples == null || voltageSamples.Length == 0)
            {
                throw new InvalidOperationException("The scope waveform has no samples.");
            }

            // Phase 2 plugs in here: fetch channel 1, the voltage across the
            // 0.1 ohm ground shunt, average it (the signal is noisy at this
            // current), and divide by 0.1 ohm for the burst current. Not in v1.

            // Prefer the interval stamped on the waveform. Fall back to the
            // rate read back at setup if the stamp is missing.
            double sampleIntervalSeconds = _sampleIntervalSeconds;
            if (waveform.Timing != null && waveform.Timing.SampleInterval.TotalSeconds > 0)
            {
                sampleIntervalSeconds = waveform.Timing.SampleInterval.TotalSeconds;
            }

            // =============================================================================
            // Waveform analysis
            // =============================================================================
            TrialResult result = WaveformAnalysis.Analyze(
                voltageSamples,
                sampleIntervalSeconds,
                _preTriggerSampleCount,
                _settings);
            result.TrialNumber = trialNumber;
            result.SampleIntervalSeconds = sampleIntervalSeconds;
            result.TriggerSampleIndex = _preTriggerSampleCount;

            // Copy the samples out of the driver's buffer before the next fetch reuses it.
            double[] voltageCopy = new double[voltageSamples.Length];
            for (int sampleIndex = 0; sampleIndex < voltageSamples.Length; sampleIndex++)
            {
                voltageCopy[sampleIndex] = voltageSamples[sampleIndex];
            }
            result.VoltageSamples = voltageCopy;
            return result;
        }

        private void CloseInstruments(bool throwOnCloseError)
        {
            Exception closeError = null;

            if (_scope != null)
            {
                try
                {
                    _scope.Measurement.Abort();
                }
                catch (Exception ex)
                {
                    closeError = ex;
                }

                try
                {
                    // Release PXI_Trig0 so the next program does not find the line still driven.
                    _scope.ExportedSignals.ReferenceTriggerOutputTerminal =
                        ScopeReferenceTriggerExportedOutputTerminal.NoSource;
                }
                catch (Exception ex)
                {
                    if (closeError == null)
                    {
                        closeError = ex;
                    }
                }

                try
                {
                    _scope.Dispose();
                }
                catch (Exception ex)
                {
                    if (closeError == null)
                    {
                        closeError = ex;
                    }
                }

                _scope = null;
                _scopeChannel = null;
            }

            if (_smu != null)
            {
                try
                {
                    // Reset returns the output to the driver's default, which is 0 V
                    // and disabled. That is how the NI single-point example finishes.
                    _smu.Utility.Reset();
                }
                catch (Exception ex)
                {
                    if (closeError == null)
                    {
                        closeError = ex;
                    }
                }

                try
                {
                    _smu.Close();
                }
                catch (Exception ex)
                {
                    if (closeError == null)
                    {
                        closeError = ex;
                    }
                }

                _smu = null;
                _smuChannel = null;
            }

            if (throwOnCloseError && closeError != null)
            {
                throw new InvalidOperationException(
                    "The trials finished, but an instrument did not close cleanly. " + closeError.Message,
                    closeError);
            }
        }
    }
}
