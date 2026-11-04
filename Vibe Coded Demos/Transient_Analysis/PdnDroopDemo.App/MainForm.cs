using System;
using System.Collections.Generic;
using System.Drawing;
using System.Threading;
using System.Windows.Forms;
using ScottPlot;
using ScottPlot.Plottable;

namespace PdnDroopDemo
{
    /// <summary>
    /// Live window for one fixed-voltage droop run. The measurement object never
    /// sees this form; it only hands back a TrialResult after each burst.
    /// </summary>
    public class MainForm : Form
    {
        private readonly DroopMeasurementSettings _settings;
        private readonly TrialResult[] _trials;
        private int _trialCount;

        private RunStatusBanner _runStatusBanner;
        private Label _statusLabel;
        private ComboBox _comChoice;
        private Button _runButton;
        private FormsPlot _waveformPlot;
        private FormsPlot _stripPlot;
        private FormsPlot _droopHistogramPlot;
        private FormsPlot _settleHistogramPlot;
        private TextBox _summaryBox;
        private Button _closeButton;

        private DroopMeasurement _measurement;
        private Thread _worker;
        private bool _runInProgress;

        public MainForm()
        {
            _settings = new DroopMeasurementSettings();
            _trials = new TrialResult[_settings.TrialCount];

            Text = "ESP32-C6 Rail Droop";
            StartPosition = FormStartPosition.CenterScreen;
            ClientSize = new Size(1100, 980);
            Font = new Font("Arial", 10);
            BackColor = Color.White;

            BuildLayout();
            FormClosing += OnFormClosing;
        }

        private void BuildLayout()
        {
            _runStatusBanner = new RunStatusBanner();

            Label infoLabel = new Label();
            infoLabel.Dock = DockStyle.Top;
            infoLabel.Height = 44;
            infoLabel.Padding = new Padding(8, 6, 8, 0);
            infoLabel.Text =
                "Fixed rail at " + _settings.RailVoltageVolts.ToString("0.00")
                + " V, AC-coupled scope (20 MHz BW). Each trial is one BLE advertising event "
                + "(ADV_IND × " + _settings.ExpectedAdvertisingPacketCount.ToString()
                + ", no SCAN_REQUEST wait), triggered by GPIO10. "
                + _settings.TrialCount.ToString() + " trials. Red line = "
                + _settings.DroopSpecLimitMillivolts.ToString("0") + " mV peak-droop limit.";

            Panel controlPanel = new Panel();
            controlPanel.Dock = DockStyle.Top;
            controlPanel.Height = 40;
            controlPanel.Padding = new Padding(8, 6, 8, 0);

            Label comLabel = new Label();
            comLabel.Text = "DUT COM";
            comLabel.AutoSize = true;
            comLabel.Location = new Point(8, 10);

            _comChoice = new ComboBox();
            _comChoice.DropDownStyle = ComboBoxStyle.DropDownList;
            _comChoice.Width = 90;
            _comChoice.Location = new Point(80, 6);
            PopulateComPorts();

            Label comHint = new Label();
            comHint.Text = "(Silicon Labs CP210x)";
            comHint.AutoSize = true;
            comHint.ForeColor = Color.FromArgb(85, 85, 85);
            comHint.Location = new Point(180, 10);

            _runButton = new Button();
            _runButton.Text = "Run";
            _runButton.Size = new Size(90, 28);
            _runButton.Location = new Point(340, 5);
            _runButton.Click += OnRunClicked;

            controlPanel.Controls.Add(comLabel);
            controlPanel.Controls.Add(_comChoice);
            controlPanel.Controls.Add(comHint);
            controlPanel.Controls.Add(_runButton);

            _statusLabel = new Label();
            _statusLabel.Dock = DockStyle.Top;
            _statusLabel.Height = 28;
            _statusLabel.Padding = new Padding(8, 4, 8, 0);
            _statusLabel.Text = "Select the DUT COM port (CP210x), then Run.";

            Panel buttonPanel = new Panel();
            buttonPanel.Dock = DockStyle.Bottom;
            buttonPanel.Height = 44;

            _closeButton = new Button();
            _closeButton.Text = "Close";
            _closeButton.Size = new Size(180, 30);
            _closeButton.Anchor = AnchorStyles.Right;
            _closeButton.Top = 6;
            _closeButton.Left = buttonPanel.Width - _closeButton.Width - 12;
            _closeButton.Click += delegate { Close(); };
            buttonPanel.Resize += delegate
            {
                _closeButton.Left = buttonPanel.Width - _closeButton.Width - 12;
            };
            buttonPanel.Controls.Add(_closeButton);

            TableLayoutPanel table = new TableLayoutPanel();
            table.Dock = DockStyle.Fill;
            table.ColumnCount = 3;
            table.RowCount = 3;
            table.Padding = new Padding(8);
            table.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 34));
            table.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 33));
            table.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 33));
            table.RowStyles.Add(new RowStyle(SizeType.Percent, 46));
            table.RowStyles.Add(new RowStyle(SizeType.Percent, 27));
            table.RowStyles.Add(new RowStyle(SizeType.Percent, 27));

            _waveformPlot = CreatePlot();
            _stripPlot = CreatePlot();
            _droopHistogramPlot = CreatePlot();
            _settleHistogramPlot = CreatePlot();

            _summaryBox = new TextBox();
            _summaryBox.Multiline = true;
            _summaryBox.ReadOnly = true;
            _summaryBox.ScrollBars = ScrollBars.Vertical;
            _summaryBox.Font = new Font("Consolas", 10);
            _summaryBox.Dock = DockStyle.Fill;
            _summaryBox.Text = "Waiting for Run.";

            table.Controls.Add(_waveformPlot, 0, 0);
            table.SetColumnSpan(_waveformPlot, 3);
            table.Controls.Add(_stripPlot, 0, 1);
            table.SetColumnSpan(_stripPlot, 3);
            table.Controls.Add(_droopHistogramPlot, 0, 2);
            table.Controls.Add(_settleHistogramPlot, 1, 2);
            table.Controls.Add(_summaryBox, 2, 2);

            LabelDroopAxes();

            // Fill is added first so the top and bottom strips keep their height.
            // Dock order: last docked Top wins the uppermost band.
            Controls.Add(table);
            Controls.Add(buttonPanel);
            Controls.Add(_statusLabel);
            Controls.Add(controlPanel);
            Controls.Add(infoLabel);
            Controls.Add(_runStatusBanner);
        }

        private void PopulateComPorts()
        {
            List<DutComPortInfo> ports = DutComPortDiscovery.ListComPorts();
            _comChoice.Items.Clear();

            if (ports.Count == 0)
            {
                _comChoice.Items.Add(DutComPortDiscovery.DefaultComLabel);
                _comChoice.SelectedIndex = 0;
                return;
            }

            string preferred = DutComPortDiscovery.PreferredComLabel(ports);
            int selectedIndex = 0;
            for (int index = 0; index < ports.Count; index++)
            {
                _comChoice.Items.Add(ports[index].Label);
                if (string.Equals(ports[index].Label, preferred, StringComparison.OrdinalIgnoreCase))
                {
                    selectedIndex = index;
                }
            }

            _comChoice.SelectedIndex = selectedIndex;
        }

        private void OnRunClicked(object sender, EventArgs args)
        {
            if (_runInProgress)
            {
                return;
            }

            string selectedCom = _comChoice.SelectedItem as string;
            if (string.IsNullOrEmpty(selectedCom))
            {
                MessageBox.Show(
                    this,
                    "Select a DUT COM port. Prefer the Silicon Labs CP210x adapter.",
                    "Rail droop",
                    MessageBoxButtons.OK,
                    MessageBoxIcon.Warning);
                return;
            }

            _settings.DutComPort = selectedCom;
            _trialCount = 0;
            for (int index = 0; index < _trials.Length; index++)
            {
                _trials[index] = null;
            }

            _comChoice.Enabled = false;
            _runButton.Enabled = false;
            _runInProgress = true;
            _runStatusBanner.SetPhase(MeasurementPhase.SettingUp);
            _summaryBox.Text = "Waiting for the first burst.";
            _statusLabel.Text =
                "Sourcing " + _settings.RailVoltageVolts.ToString("0.00") + " V / "
                + (_settings.CurrentLimitAmps * 1000.0).ToString("0")
                + " mA, resetting DUT on " + selectedCom
                + ", then confirming advertising (GPIO10)...";

            StartRun();
        }

        private static FormsPlot CreatePlot()
        {
            FormsPlot plot = new FormsPlot();
            plot.Dock = DockStyle.Fill;
            plot.Plot.Style(figureBackground: Color.White, dataBackground: Color.White);
            plot.Plot.Grid(true);
            return plot;
        }

        private void LabelDroopAxes()
        {
            _waveformPlot.Plot.Title("Latest advertising event");
            _waveformPlot.Plot.XLabel("Time from GPIO10 (µs)");
            _waveformPlot.Plot.YLabel("ΔV from quiet baseline (mV)");

            _stripPlot.Plot.Title("Peak droop of each advertising event");
            _stripPlot.Plot.XLabel("Trial");
            _stripPlot.Plot.YLabel("Peak droop (mV)");

            _droopHistogramPlot.Plot.Title("Peak droop");
            _droopHistogramPlot.Plot.XLabel("Peak droop (mV)");
            _droopHistogramPlot.Plot.YLabel("Trials");

            _settleHistogramPlot.Plot.Title("Burst-active width");
            _settleHistogramPlot.Plot.XLabel("First→last ADV_IND (µs)");
            _settleHistogramPlot.Plot.YLabel("Trials");
        }

        private void StartRun()
        {
            if (_measurement != null)
            {
                _measurement.Dispose();
                _measurement = null;
            }

            _measurement = new DroopMeasurement(_settings);
            _worker = new Thread(RunMeasurement);
            _worker.IsBackground = true;
            _worker.Name = "PDN droop measurement";
            _worker.Start();
        }

        private void RunMeasurement()
        {
            try
            {
                DiscoveredPxiInstruments discovered = _settings.ResolveInstrumentResources();
                if (discovered != null)
                {
                    string status =
                        "Using " + _settings.ScopeResourceName
                        + ", " + _settings.SmuResourceName
                        + " @ " + _settings.RailVoltageVolts.ToString("0.00") + " V / "
                        + (_settings.CurrentLimitAmps * 1000.0).ToString("0") + " mA"
                        + " (arb " + _settings.FgenResourceName + "), DUT "
                        + _settings.DutComPort + ", trigger "
                        + _settings.ScopeTriggerSource
                        + ". Confirming advertising...";
                    PostToForm(delegate { _statusLabel.Text = status; });
                }

                DroopStatistics statistics = _measurement.RunTrials(ReportTrial, ReportPhase);
                PostToForm(delegate { ShowFinished(statistics); });
            }
            catch (Exception ex)
            {
                Exception error = ex;
                PostToForm(delegate { ShowError(error); });
            }
        }

        private void ReportPhase(MeasurementPhase phase)
        {
            PostToForm(delegate { _runStatusBanner.SetPhase(phase); });
        }

        /// <summary>
        /// Posts work to the UI thread. If the window is already gone, the
        /// measurement thread just returns; the sessions were closed in RunTrials.
        /// </summary>
        private void PostToForm(MethodInvoker action)
        {
            if (IsDisposed || !IsHandleCreated)
            {
                return;
            }

            try
            {
                BeginInvoke(action);
            }
            catch (InvalidOperationException)
            {
                // The form closed between the check and the post.
            }
        }

        /// <summary>
        /// RunTrials calls this on the measurement thread, once per burst.
        /// WinForms controls may only be changed on the thread that created the
        /// form, so the first call posts itself back here with BeginInvoke and
        /// returns. The second call is on the UI thread and updates the plots.
        /// </summary>
        private void ReportTrial(TrialResult trial)
        {
            if (IsDisposed || !IsHandleCreated)
            {
                return;
            }

            if (InvokeRequired)
            {
                TrialResult trialToApply = trial;
                PostToForm(delegate { ReportTrial(trialToApply); });
                return;
            }

            if (_trialCount >= _trials.Length)
            {
                return;
            }

            _trials[_trialCount] = trial;
            _trialCount = _trialCount + 1;

            string timingText = "burst " + trial.BurstActiveMicroseconds.ToString("0") + " µs";
            if (trial.DidSettle)
            {
                timingText = timingText + ", 90% recovery " + trial.SettleTimeMicroseconds.ToString("0") + " µs";
            }

            string packetText = trial.PacketCount.ToString() + "/"
                + trial.ExpectedPacketCount.ToString() + " packets";
            string reboundText = "";
            if (trial.InterPacketReboundPercent != null && trial.InterPacketReboundPercent.Length > 0)
            {
                reboundText = ", rebound " + trial.MeanInterPacketReboundPercent.ToString("0") + "%";
            }

            _statusLabel.Text =
                "Trial " + trial.TrialNumber.ToString() + " of " + _settings.TrialCount.ToString()
                + ":  peak droop " + trial.DroopMillivolts.ToString("0.0") + " mV,  "
                + packetText + reboundText + ",  " + timingText;

            Redraw();
        }

        private void Redraw()
        {
            TrialResult[] completed = new TrialResult[_trialCount];
            for (int trialIndex = 0; trialIndex < _trialCount; trialIndex++)
            {
                completed[trialIndex] = _trials[trialIndex];
            }

            DrawWaveform(completed[completed.Length - 1]);
            DrawStrip(completed);
            DroopStatistics statistics = DroopStatistics.FromTrials(completed, _settings);
            DrawHistogram(
                _droopHistogramPlot,
                statistics.DroopHistogramCentersMillivolts,
                statistics.DroopHistogramCounts,
                "Peak droop",
                "Peak droop (mV)");

            // Prefer 90% recovery when the record caught it; otherwise show the
            // always-available first→last ADV_IND width (aligned with this capture).
            if (statistics.SettledCount > 0)
            {
                DrawHistogram(
                    _settleHistogramPlot,
                    statistics.SettleHistogramCentersMicroseconds,
                    statistics.SettleHistogramCounts,
                    "Post-burst 90% recovery",
                    "After last ADV_IND (µs)");
            }
            else
            {
                DrawHistogram(
                    _settleHistogramPlot,
                    statistics.BurstActiveHistogramCentersMicroseconds,
                    statistics.BurstActiveHistogramCounts,
                    "Burst-active width",
                    "First→last ADV_IND (µs)");
            }
            _summaryBox.Text = statistics.FormatSummary();
        }

        private void DrawWaveform(TrialResult trial)
        {
            _waveformPlot.Plot.Clear();
            _waveformPlot.Plot.Title(
                "Latest event, trial " + trial.TrialNumber.ToString()
                + "  (" + trial.PacketCount.ToString() + " ADV_IND)");
            _waveformPlot.Plot.XLabel("Time from GPIO10 (µs)");
            _waveformPlot.Plot.YLabel("ΔV from quiet baseline (mV)");

            if (trial.VoltageSamples == null || trial.VoltageSamples.Length == 0 || trial.SampleIntervalSeconds <= 0)
            {
                _waveformPlot.Refresh();
                return;
            }

            // Plot millivolts relative to the pre-trigger baseline so AC and DC
            // captures look the same: quiet rail at 0, droop negative.
            int sampleCount = trial.VoltageSamples.Length;
            double[] timeMicroseconds = new double[sampleCount];
            double[] deltaMillivolts = new double[sampleCount];
            for (int sampleIndex = 0; sampleIndex < sampleCount; sampleIndex++)
            {
                timeMicroseconds[sampleIndex] =
                    (sampleIndex - trial.TriggerSampleIndex) * trial.SampleIntervalSeconds * 1e6;
                deltaMillivolts[sampleIndex] =
                    (trial.VoltageSamples[sampleIndex] - trial.NominalVolts) * 1000.0;
            }

            ScatterPlot trace = _waveformPlot.Plot.AddScatter(
                timeMicroseconds,
                deltaMillivolts,
                color: Color.FromArgb(31, 119, 180),
                lineWidth: 1,
                markerSize: 0);
            trace.Label = "ΔV";

            HLine nominalLine = _waveformPlot.Plot.AddHorizontalLine(
                0,
                color: Color.FromArgb(44, 160, 44),
                width: 1.5f,
                style: LineStyle.Dash);
            nominalLine.Label = "quiet baseline";

            HLine specLine = _waveformPlot.Plot.AddHorizontalLine(
                -_settings.DroopSpecLimitMillivolts,
                color: Color.FromArgb(214, 39, 40),
                width: 1.5f,
                style: LineStyle.Solid);
            specLine.Label = _settings.DroopSpecLimitMillivolts.ToString("0") + " mV spec";

            VLine triggerLine = _waveformPlot.Plot.AddVerticalLine(
                0,
                color: Color.FromArgb(214, 39, 40),
                width: 1.5f,
                style: LineStyle.Dash);
            triggerLine.Label = "GPIO10";

            // Mark the end of each detected ADV_IND so post-burst settle is visible.
            if (trial.PacketEndIndices != null)
            {
                for (int packetIndex = 0; packetIndex < trial.PacketEndIndices.Length; packetIndex++)
                {
                    double packetEndMicroseconds =
                        (trial.PacketEndIndices[packetIndex] - trial.TriggerSampleIndex)
                        * trial.SampleIntervalSeconds * 1e6;
                    VLine packetEndLine = _waveformPlot.Plot.AddVerticalLine(
                        packetEndMicroseconds,
                        color: Color.FromArgb(255, 127, 14),
                        width: 1,
                        style: LineStyle.Dot);
                    if (packetIndex == trial.PacketEndIndices.Length - 1)
                    {
                        packetEndLine.Label = "last ADV_IND end";
                    }
                }
            }

            _waveformPlot.Plot.Legend(location: Alignment.LowerRight);
            _waveformPlot.Plot.AxisAuto();
            _waveformPlot.Refresh();
        }

        private void DrawStrip(TrialResult[] completed)
        {
            int passCount = 0;
            int failCount = 0;
            for (int trialIndex = 0; trialIndex < completed.Length; trialIndex++)
            {
                if (completed[trialIndex].PassedDroopSpec)
                {
                    passCount = passCount + 1;
                }
                else
                {
                    failCount = failCount + 1;
                }
            }

            double[] passTrial = new double[passCount];
            double[] passDroopMillivolts = new double[passCount];
            double[] failTrial = new double[failCount];
            double[] failDroopMillivolts = new double[failCount];
            int passIndex = 0;
            int failIndex = 0;
            for (int trialIndex = 0; trialIndex < completed.Length; trialIndex++)
            {
                if (completed[trialIndex].PassedDroopSpec)
                {
                    passTrial[passIndex] = completed[trialIndex].TrialNumber;
                    passDroopMillivolts[passIndex] = completed[trialIndex].DroopMillivolts;
                    passIndex = passIndex + 1;
                }
                else
                {
                    failTrial[failIndex] = completed[trialIndex].TrialNumber;
                    failDroopMillivolts[failIndex] = completed[trialIndex].DroopMillivolts;
                    failIndex = failIndex + 1;
                }
            }

            _stripPlot.Plot.Clear();
            _stripPlot.Plot.Title("Peak droop of each advertising event");
            _stripPlot.Plot.XLabel("Trial");
            _stripPlot.Plot.YLabel("Peak droop (mV)");

            if (passCount > 0)
            {
                ScatterPlot passSeries = _stripPlot.Plot.AddScatter(
                    passTrial,
                    passDroopMillivolts,
                    color: Color.FromArgb(31, 119, 180),
                    lineWidth: 0,
                    markerSize: 8);
                passSeries.Label = "at or under spec";
            }

            if (failCount > 0)
            {
                ScatterPlot failSeries = _stripPlot.Plot.AddScatter(
                    failTrial,
                    failDroopMillivolts,
                    color: Color.FromArgb(214, 39, 40),
                    lineWidth: 0,
                    markerSize: 9,
                    markerShape: MarkerShape.cross);
                failSeries.Label = "over spec";
            }

            HLine specLine = _stripPlot.Plot.AddHorizontalLine(
                _settings.DroopSpecLimitMillivolts,
                color: Color.FromArgb(214, 39, 40),
                width: 1.5f,
                style: LineStyle.Dash);
            specLine.Label = "spec limit";

            _stripPlot.Plot.Legend(location: Alignment.UpperRight);
            _stripPlot.Plot.SetAxisLimitsX(0, _settings.TrialCount + 1);
            _stripPlot.Plot.AxisAutoY();
            _stripPlot.Refresh();
        }

        private static void DrawHistogram(
            FormsPlot plot,
            double[] centers,
            int[] counts,
            string title,
            string xLabel)
        {
            plot.Plot.Clear();
            plot.Plot.Title(title);
            plot.Plot.XLabel(xLabel);
            plot.Plot.YLabel("Trials");

            if (centers != null && counts != null && centers.Length > 0)
            {
                double[] countValues = new double[counts.Length];
                for (int bin = 0; bin < counts.Length; bin++)
                {
                    countValues[bin] = counts[bin];
                }

                BarPlot bars = plot.Plot.AddBar(countValues, centers);
                bars.FillColor = Color.FromArgb(44, 160, 44);
                bars.BorderColor = Color.FromArgb(44, 160, 44);
                if (centers.Length >= 2)
                {
                    bars.BarWidth = Math.Abs(centers[1] - centers[0]) * 0.9;
                }
            }

            plot.Plot.AxisAuto();
            plot.Refresh();
        }

        private void ShowFinished(DroopStatistics statistics)
        {
            if (IsDisposed)
            {
                return;
            }

            if (statistics.TrialCount == 0)
            {
                _statusLabel.Text = "Stopped before any burst was captured.";
            }
            else
            {
                _statusLabel.Text =
                    "Run complete.  " + statistics.PassCount.ToString() + " of "
                    + statistics.TrialCount.ToString() + " trials at or under "
                    + _settings.DroopSpecLimitMillivolts.ToString("0") + " mV.";
            }

            _runInProgress = false;
            _comChoice.Enabled = true;
            _runButton.Enabled = true;
            _runStatusBanner.SetPhase(MeasurementPhase.Ready);
            _closeButton.Text = "Close (Run Complete)";
            _closeButton.Width = 200;
            _closeButton.Left = _closeButton.Parent.Width - _closeButton.Width - 12;
        }

        private void ShowError(Exception ex)
        {
            if (IsDisposed)
            {
                return;
            }

            _runInProgress = false;
            _comChoice.Enabled = true;
            _runButton.Enabled = true;
            _runStatusBanner.SetPhase(MeasurementPhase.Ready);
            _statusLabel.Text = "The run stopped on an error.";
            _closeButton.Text = "Close (Run Complete)";
            MessageBox.Show(
                this,
                ex.Message,
                "Rail droop",
                MessageBoxButtons.OK,
                MessageBoxIcon.Error);
        }

        private void OnFormClosing(object sender, FormClosingEventArgs args)
        {
            if (_measurement != null)
            {
                _measurement.StopRequested = true;
            }

            // Give the burst in flight time to finish and close the SMU. The
            // trigger timeout is the longest the worker should still be blocked.
            bool workerStillRunning = false;
            if (_worker != null && _worker.IsAlive && _worker != Thread.CurrentThread)
            {
                int waitMilliseconds = (int)((
                    _settings.ScopeTriggerTimeoutSeconds
                    + _settings.DutResetAdvertiseWaitSeconds
                    + FetchTimeoutSeconds
                    + 1.0) * 1000.0);
                workerStillRunning = !_worker.Join(waitMilliseconds);
            }

            // RunTrials already closes both sessions in a finally block. Dispose
            // again only when that finally has finished, so two threads do not
            // close the SMU at the same time.
            if (_measurement != null && !workerStillRunning)
            {
                _measurement.Dispose();
                _measurement = null;
            }
        }

        // Same constant the measurement uses for the fetch, so the close wait
        // covers a fetch that is still in progress. Kept here as a number the
        // form can see without reaching into the measurement.
        private const double FetchTimeoutSeconds = 5.0;
    }
}
