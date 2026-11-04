using System;

namespace PdnDroopDemo
{
    /// <summary>
    /// Coarse run phase for the GUI status LED. SettingUp is instrument/DUT work;
    /// Running is when scope captures are producing trial data.
    /// </summary>
    public enum MeasurementPhase
    {
        Ready,
        SettingUp,
        Running
    }

    /// <summary>
    /// One advertising burst: peak droop across the ADV_IND packets, and how long
    /// the rail took to recover after the last packet.
    /// </summary>
    public class TrialResult
    {
        /// <summary>1 for the first burst, then 2, and so on.</summary>
        public int TrialNumber { get; set; }

        /// <summary>
        /// Quiet baseline from the samples before the trigger, in volts.
        /// Near 0 V when the scope is AC-coupled; the rail voltage when DC-coupled.
        /// </summary>
        public double NominalVolts { get; set; }

        /// <summary>
        /// Deepest dip in the advertising event, in millivolts below the baseline.
        /// With three back-to-back ADV_IND packets this is the max of the three.
        /// </summary>
        public double DroopMillivolts { get; set; }

        /// <summary>
        /// Time from the end of the last ADV_IND until the rail has recovered the
        /// configured fraction of the peak droop (default 90%). Zero when DidSettle
        /// is false. Not measured from the global minimum.
        /// </summary>
        public double SettleTimeMicroseconds { get; set; }

        /// <summary>
        /// Time from the start of the first ADV_IND until post-burst recovery.
        /// Zero when DidSettle is false.
        /// </summary>
        public double BurstDurationMicroseconds { get; set; }

        /// <summary>
        /// Time from the first ADV_IND edge to the last ADV_IND exit. Available
        /// whenever packets were detected, even if post-burst recovery was cut off.
        /// </summary>
        public double BurstActiveMicroseconds { get; set; }

        /// <summary>False when the record ended before the rail met the recovery criterion.</summary>
        public bool DidSettle { get; set; }

        /// <summary>True when DroopMillivolts is at or under the spec limit.</summary>
        public bool PassedDroopSpec { get; set; }

        /// <summary>How many ADV_IND current dips were found after the trigger.</summary>
        public int PacketCount { get; set; }

        /// <summary>How many packets the firmware is expected to send (3 for legacy ADV on 37/38/39).</summary>
        public int ExpectedPacketCount { get; set; }

        /// <summary>True when PacketCount equals ExpectedPacketCount.</summary>
        public bool PacketCountMatchesExpected { get; set; }

        /// <summary>Droop of each detected packet, in millivolts, oldest first.</summary>
        public double[] PacketDroopMillivolts { get; set; }

        /// <summary>Sample index where each packet droop started.</summary>
        public int[] PacketStartIndices { get; set; }

        /// <summary>Sample index where each packet droop ended (rail rose past the exit threshold).</summary>
        public int[] PacketEndIndices { get; set; }

        /// <summary>
        /// How far toward the baseline the rail climbed between packets, as a
        /// percent of that packet's droop. Empty when fewer than two packets.
        /// </summary>
        public double[] InterPacketReboundPercent { get; set; }

        /// <summary>Average of InterPacketReboundPercent, or 0 when there were no gaps.</summary>
        public double MeanInterPacketReboundPercent { get; set; }

        /// <summary>Rail voltage (or AC deviation) for this burst, in volts, oldest sample first.</summary>
        public double[] VoltageSamples { get; set; }

        /// <summary>Time between VoltageSamples, in seconds.</summary>
        public double SampleIntervalSeconds { get; set; }

        /// <summary>Index of the GPIO10 trigger inside VoltageSamples. Samples before this are the quiet baseline.</summary>
        public int TriggerSampleIndex { get; set; }
    }

    /// <summary>
    /// Mean, spread, and histograms for one run. Settle-time numbers use only the
    /// trials that actually recovered inside the record.
    /// </summary>
    public class DroopStatistics
    {
        /// <summary>Trials included in this summary.</summary>
        public int TrialCount { get; set; }

        /// <summary>Trials whose droop was at or under the spec limit.</summary>
        public int PassCount { get; set; }

        /// <summary>Trials that recovered inside the record. Settle-time stats use this set.</summary>
        public int SettledCount { get; set; }

        /// <summary>Trials whose detected packet count matched the expected ADV_IND count.</summary>
        public int ExpectedPacketMatchCount { get; set; }

        /// <summary>The droop limit these trials were judged against, in millivolts.</summary>
        public double DroopSpecLimitMillivolts { get; set; }

        /// <summary>Average peak droop across every trial, in millivolts.</summary>
        public double DroopMeanMillivolts { get; set; }

        /// <summary>Sample standard deviation of droop (divide by N minus 1), in millivolts.</summary>
        public double DroopStandardDeviationMillivolts { get; set; }

        /// <summary>Shallowest peak dip in the run, in millivolts.</summary>
        public double DroopMinimumMillivolts { get; set; }

        /// <summary>Deepest peak dip in the run, in millivolts.</summary>
        public double DroopMaximumMillivolts { get; set; }

        /// <summary>Average post-burst recovery time of the trials that settled, in microseconds.</summary>
        public double SettleMeanMicroseconds { get; set; }

        /// <summary>Sample standard deviation of post-burst recovery time, in microseconds.</summary>
        public double SettleStandardDeviationMicroseconds { get; set; }

        /// <summary>Fastest post-burst recovery among trials that settled, in microseconds.</summary>
        public double SettleMinimumMicroseconds { get; set; }

        /// <summary>Slowest post-burst recovery among trials that settled, in microseconds.</summary>
        public double SettleMaximumMicroseconds { get; set; }

        /// <summary>Average advertising-event duration (first packet start to recovered), in microseconds.</summary>
        public double BurstDurationMeanMicroseconds { get; set; }

        /// <summary>Average first-to-last ADV_IND width across trials with packets, in microseconds.</summary>
        public double BurstActiveMeanMicroseconds { get; set; }

        /// <summary>Sample standard deviation of burst-active width, in microseconds.</summary>
        public double BurstActiveStandardDeviationMicroseconds { get; set; }

        /// <summary>How many trials contributed to burst-active stats.</summary>
        public int BurstActiveCount { get; set; }

        /// <summary>Center of each burst-active histogram bin, in microseconds.</summary>
        public double[] BurstActiveHistogramCentersMicroseconds { get; set; }

        /// <summary>How many trials fell in each burst-active bin.</summary>
        public int[] BurstActiveHistogramCounts { get; set; }

        /// <summary>Average inter-packet rebound across trials that had at least one gap, in percent.</summary>
        public double ReboundMeanPercent { get; set; }

        /// <summary>True when at least one trial reported an inter-packet rebound.</summary>
        public bool ReboundIsValid { get; set; }

        /// <summary>
        /// One-sided process capability against the droop limit.
        /// Meaningful only when DroopCpkIsValid is true.
        /// </summary>
        public double DroopCpk { get; set; }

        /// <summary>False when fewer than two trials, or every droop was identical, so Cpk would divide by zero.</summary>
        public bool DroopCpkIsValid { get; set; }

        /// <summary>Center of each droop histogram bin, in millivolts.</summary>
        public double[] DroopHistogramCentersMillivolts { get; set; }

        /// <summary>How many trials fell in each droop bin.</summary>
        public int[] DroopHistogramCounts { get; set; }

        /// <summary>Center of each post-burst settling-time histogram bin, in microseconds.</summary>
        public double[] SettleHistogramCentersMicroseconds { get; set; }

        /// <summary>How many settled trials fell in each settling-time bin.</summary>
        public int[] SettleHistogramCounts { get; set; }

        /// <summary>
        /// Build the summary for a finished run. trials may be a partial set if the
        /// window was closed early.
        /// </summary>
        public static DroopStatistics FromTrials(TrialResult[] trials, DroopMeasurementSettings settings)
        {
            DroopStatistics statistics = new DroopStatistics();
            statistics.DroopSpecLimitMillivolts = settings.DroopSpecLimitMillivolts;
            statistics.DroopHistogramCentersMillivolts = new double[0];
            statistics.DroopHistogramCounts = new int[0];
            statistics.SettleHistogramCentersMicroseconds = new double[0];
            statistics.SettleHistogramCounts = new int[0];
            statistics.BurstActiveHistogramCentersMicroseconds = new double[0];
            statistics.BurstActiveHistogramCounts = new int[0];

            if (trials == null || trials.Length == 0)
            {
                return statistics;
            }

            int trialCount = trials.Length;
            statistics.TrialCount = trialCount;

            double[] droopMillivolts = new double[trialCount];
            int settledCount = 0;
            int burstActiveCount = 0;
            int reboundTrialCount = 0;
            double reboundSum = 0;
            for (int trialIndex = 0; trialIndex < trialCount; trialIndex++)
            {
                droopMillivolts[trialIndex] = trials[trialIndex].DroopMillivolts;
                if (trials[trialIndex].PassedDroopSpec)
                {
                    statistics.PassCount = statistics.PassCount + 1;
                }
                if (trials[trialIndex].DidSettle)
                {
                    settledCount = settledCount + 1;
                }
                if (trials[trialIndex].PacketCount > 0 && trials[trialIndex].BurstActiveMicroseconds > 0)
                {
                    burstActiveCount = burstActiveCount + 1;
                }
                if (trials[trialIndex].PacketCountMatchesExpected)
                {
                    statistics.ExpectedPacketMatchCount = statistics.ExpectedPacketMatchCount + 1;
                }
                if (trials[trialIndex].InterPacketReboundPercent != null
                    && trials[trialIndex].InterPacketReboundPercent.Length > 0)
                {
                    reboundSum = reboundSum + trials[trialIndex].MeanInterPacketReboundPercent;
                    reboundTrialCount = reboundTrialCount + 1;
                }
            }

            double droopMean;
            double droopStandardDeviation;
            double droopMinimum;
            double droopMaximum;
            MeanAndSpread(
                droopMillivolts,
                trialCount,
                out droopMean,
                out droopStandardDeviation,
                out droopMinimum,
                out droopMaximum);
            statistics.DroopMeanMillivolts = droopMean;
            statistics.DroopStandardDeviationMillivolts = droopStandardDeviation;
            statistics.DroopMinimumMillivolts = droopMinimum;
            statistics.DroopMaximumMillivolts = droopMaximum;

            // One-sided Cpk. The spec is an upper limit on droop (a deeper dip is
            // worse, a shallower dip is fine), so there is no lower spec limit.
            // Cpk = (upper limit - mean) / (3 * sample standard deviation).
            // Below 1, the tail of a normal distribution crosses the limit.
            if (trialCount >= 2 && droopStandardDeviation > 0)
            {
                statistics.DroopCpk =
                    (settings.DroopSpecLimitMillivolts - droopMean) / (3.0 * droopStandardDeviation);
                statistics.DroopCpkIsValid = true;
            }

            double[] droopCenters;
            int[] droopCounts;
            FillHistogram(
                droopMillivolts,
                trialCount,
                settings.HistogramBinCount,
                out droopCenters,
                out droopCounts);
            statistics.DroopHistogramCentersMillivolts = droopCenters;
            statistics.DroopHistogramCounts = droopCounts;

            if (reboundTrialCount > 0)
            {
                statistics.ReboundIsValid = true;
                statistics.ReboundMeanPercent = reboundSum / reboundTrialCount;
            }

            statistics.BurstActiveCount = burstActiveCount;
            if (burstActiveCount > 0)
            {
                double[] burstActiveMicroseconds = new double[burstActiveCount];
                int burstActiveIndex = 0;
                for (int trialIndex = 0; trialIndex < trialCount; trialIndex++)
                {
                    if (trials[trialIndex].PacketCount > 0 && trials[trialIndex].BurstActiveMicroseconds > 0)
                    {
                        burstActiveMicroseconds[burstActiveIndex] = trials[trialIndex].BurstActiveMicroseconds;
                        burstActiveIndex = burstActiveIndex + 1;
                    }
                }

                double burstActiveMean;
                double burstActiveStandardDeviation;
                double burstActiveMinimum;
                double burstActiveMaximum;
                MeanAndSpread(
                    burstActiveMicroseconds,
                    burstActiveCount,
                    out burstActiveMean,
                    out burstActiveStandardDeviation,
                    out burstActiveMinimum,
                    out burstActiveMaximum);
                statistics.BurstActiveMeanMicroseconds = burstActiveMean;
                statistics.BurstActiveStandardDeviationMicroseconds = burstActiveStandardDeviation;

                double[] burstActiveCenters;
                int[] burstActiveCounts;
                FillHistogram(
                    burstActiveMicroseconds,
                    burstActiveCount,
                    settings.HistogramBinCount,
                    out burstActiveCenters,
                    out burstActiveCounts);
                statistics.BurstActiveHistogramCentersMicroseconds = burstActiveCenters;
                statistics.BurstActiveHistogramCounts = burstActiveCounts;
            }

            statistics.SettledCount = settledCount;
            if (settledCount > 0)
            {
                double[] settleTimeMicroseconds = new double[settledCount];
                double[] burstDurationMicroseconds = new double[settledCount];
                int settledIndex = 0;
                for (int trialIndex = 0; trialIndex < trialCount; trialIndex++)
                {
                    if (trials[trialIndex].DidSettle)
                    {
                        settleTimeMicroseconds[settledIndex] = trials[trialIndex].SettleTimeMicroseconds;
                        burstDurationMicroseconds[settledIndex] = trials[trialIndex].BurstDurationMicroseconds;
                        settledIndex = settledIndex + 1;
                    }
                }

                double settleMean;
                double settleStandardDeviation;
                double settleMinimum;
                double settleMaximum;
                MeanAndSpread(
                    settleTimeMicroseconds,
                    settledCount,
                    out settleMean,
                    out settleStandardDeviation,
                    out settleMinimum,
                    out settleMaximum);
                statistics.SettleMeanMicroseconds = settleMean;
                statistics.SettleStandardDeviationMicroseconds = settleStandardDeviation;
                statistics.SettleMinimumMicroseconds = settleMinimum;
                statistics.SettleMaximumMicroseconds = settleMaximum;

                double burstMean;
                double burstStandardDeviation;
                double burstMinimum;
                double burstMaximum;
                MeanAndSpread(
                    burstDurationMicroseconds,
                    settledCount,
                    out burstMean,
                    out burstStandardDeviation,
                    out burstMinimum,
                    out burstMaximum);
                statistics.BurstDurationMeanMicroseconds = burstMean;

                double[] settleCenters;
                int[] settleCounts;
                FillHistogram(
                    settleTimeMicroseconds,
                    settledCount,
                    settings.HistogramBinCount,
                    out settleCenters,
                    out settleCounts);
                statistics.SettleHistogramCentersMicroseconds = settleCenters;
                statistics.SettleHistogramCounts = settleCounts;
            }

            return statistics;
        }

        /// <summary>Plain-language block for the window. The same numbers are on the properties above.</summary>
        public string FormatSummary()
        {
            if (TrialCount == 0)
            {
                return "No trials completed.";
            }

            string text = "";
            text = text + "Trials: " + TrialCount.ToString() + System.Environment.NewLine;
            text = text + "Passed droop spec: " + PassCount.ToString() + " of " + TrialCount.ToString();
            text = text + "  (limit " + DroopSpecLimitMillivolts.ToString("0") + " mV)" + System.Environment.NewLine;
            text = text + "ADV_IND packets: " + ExpectedPacketMatchCount.ToString() + " of "
                + TrialCount.ToString() + " trials saw the expected count" + System.Environment.NewLine;
            text = text + System.Environment.NewLine;
            text = text + "Peak droop (mV)" + System.Environment.NewLine;
            text = text + "  mean  " + DroopMeanMillivolts.ToString("0.0") + System.Environment.NewLine;
            text = text + "  stdev " + DroopStandardDeviationMillivolts.ToString("0.0") + System.Environment.NewLine;
            text = text + "  min   " + DroopMinimumMillivolts.ToString("0.0") + System.Environment.NewLine;
            text = text + "  max   " + DroopMaximumMillivolts.ToString("0.0") + System.Environment.NewLine;

            if (DroopCpkIsValid)
            {
                text = text + "  Cpk   " + DroopCpk.ToString("0.00");
                text = text + "   (limit - mean) / (3 * stdev)" + System.Environment.NewLine;
            }
            else
            {
                text = text + "  Cpk   n/a  (need two trials that are not identical)" + System.Environment.NewLine;
            }

            text = text + System.Environment.NewLine;
            text = text + "Burst-active width (µs, first→last ADV_IND)" + System.Environment.NewLine;
            if (BurstActiveCount == 0)
            {
                text = text + "  n/a  (no ADV_IND dips detected)" + System.Environment.NewLine;
            }
            else
            {
                text = text + "  mean  " + BurstActiveMeanMicroseconds.ToString("0") + System.Environment.NewLine;
                text = text + "  stdev " + BurstActiveStandardDeviationMicroseconds.ToString("0") + System.Environment.NewLine;
            }

            text = text + System.Environment.NewLine;
            text = text + "Post-burst 90% recovery (µs)" + System.Environment.NewLine;
            if (SettledCount == 0)
            {
                text = text + "  none recovered inside the record (need more post-burst samples)" + System.Environment.NewLine;
            }
            else
            {
                text = text + "  " + SettledCount.ToString() + " of " + TrialCount.ToString()
                    + " recovered after the last ADV_IND" + System.Environment.NewLine;
                text = text + "  mean  " + SettleMeanMicroseconds.ToString("0") + System.Environment.NewLine;
                text = text + "  stdev " + SettleStandardDeviationMicroseconds.ToString("0") + System.Environment.NewLine;
                text = text + "  min   " + SettleMinimumMicroseconds.ToString("0") + System.Environment.NewLine;
                text = text + "  max   " + SettleMaximumMicroseconds.ToString("0") + System.Environment.NewLine;
            }

            text = text + System.Environment.NewLine;
            text = text + "Inter-packet rebound" + System.Environment.NewLine;
            if (!ReboundIsValid)
            {
                text = text + "  n/a  (need at least two ADV_IND dips per trial)" + System.Environment.NewLine;
            }
            else
            {
                text = text + "  mean  " + ReboundMeanPercent.ToString("0")
                    + "% of the way back to baseline between packets" + System.Environment.NewLine;
            }

            return text;
        }

        /// <summary>
        /// Sample mean and sample standard deviation. Standard deviation is 0 when
        /// fewer than two values are present, because N-1 would be zero.
        /// </summary>
        private static void MeanAndSpread(
            double[] values,
            int count,
            out double mean,
            out double standardDeviation,
            out double minimum,
            out double maximum)
        {
            double sum = 0;
            minimum = values[0];
            maximum = values[0];
            for (int index = 0; index < count; index++)
            {
                sum = sum + values[index];
                if (values[index] < minimum)
                {
                    minimum = values[index];
                }
                if (values[index] > maximum)
                {
                    maximum = values[index];
                }
            }

            mean = sum / count;

            if (count < 2)
            {
                standardDeviation = 0;
                return;
            }

            double sumOfSquares = 0;
            for (int index = 0; index < count; index++)
            {
                double delta = values[index] - mean;
                sumOfSquares = sumOfSquares + (delta * delta);
            }

            standardDeviation = Math.Sqrt(sumOfSquares / (count - 1));
        }

        /// <summary>
        /// Equal-width bins from the smallest value to the largest. The largest
        /// value lands in the last bin, because it sits exactly on the top edge.
        /// </summary>
        private static void FillHistogram(
            double[] values,
            int count,
            int binCount,
            out double[] centers,
            out int[] counts)
        {
            double minimum = values[0];
            double maximum = values[0];
            for (int index = 1; index < count; index++)
            {
                if (values[index] < minimum)
                {
                    minimum = values[index];
                }
                if (values[index] > maximum)
                {
                    maximum = values[index];
                }
            }

            // A run of identical numbers has no width. Give it a 1-unit span so
            // the bar still has a place to stand.
            double low = minimum;
            double high = maximum;
            if (high <= low)
            {
                low = minimum - 0.5;
                high = minimum + 0.5;
            }

            double binWidth = (high - low) / binCount;
            centers = new double[binCount];
            counts = new int[binCount];
            for (int bin = 0; bin < binCount; bin++)
            {
                centers[bin] = low + ((bin + 0.5) * binWidth);
            }

            for (int index = 0; index < count; index++)
            {
                int bin = (int)((values[index] - low) / binWidth);
                if (bin < 0)
                {
                    bin = 0;
                }
                if (bin >= binCount)
                {
                    bin = binCount - 1;
                }
                counts[bin] = counts[bin] + 1;
            }
        }
    }
}
