using System;
using System.Collections.Generic;

namespace PdnDroopDemo
{
    /// <summary>
    /// Turns one scope record into peak droop, per-packet dips, and post-burst recovery.
    /// Firmware that skips the SCAN_REQUEST window sends ADV_IND on 37/38/39 back to
    /// back, so the rail only fully recovers after the third packet.
    /// </summary>
    public static class WaveformAnalysis
    {
        private struct PacketDip
        {
            public int StartIndex;
            public int EndIndex;
            public int MinimumIndex;
            public double DroopMillivolts;
        }

        /// <summary>
        /// Measure one advertising burst.
        /// voltageSamples is the rail (DC) or AC-coupled deviation (AC), oldest first.
        /// The trigger is at preTriggerSampleCount: everything before that index
        /// is the quiet baseline, everything from that index on is the burst.
        /// </summary>
        public static TrialResult Analyze(
            double[] voltageSamples,
            double sampleIntervalSeconds,
            int preTriggerSampleCount,
            DroopMeasurementSettings settings)
        {
            if (voltageSamples == null || voltageSamples.Length == 0)
            {
                throw new ArgumentException("The scope record is empty.");
            }
            if (sampleIntervalSeconds <= 0)
            {
                throw new ArgumentException("Sample interval must be positive.");
            }
            if (preTriggerSampleCount < 1)
            {
                throw new ArgumentException(
                    "The record has no pre-trigger samples, so the undisturbed rail voltage cannot be estimated.");
            }
            if (preTriggerSampleCount >= voltageSamples.Length)
            {
                throw new ArgumentException(
                    "The trigger is at or past the end of the record, so there is no burst to measure.");
            }

            TrialResult result = new TrialResult();

            // Quiet baseline: AC-coupled this is near 0 V; DC-coupled it is the rail.
            double nominalSumVolts = 0;
            for (int sampleIndex = 0; sampleIndex < preTriggerSampleCount; sampleIndex++)
            {
                nominalSumVolts = nominalSumVolts + voltageSamples[sampleIndex];
            }
            double nominalVolts = nominalSumVolts / preTriggerSampleCount;
            result.NominalVolts = nominalVolts;

            List<PacketDip> packets = FindPacketDips(
                voltageSamples,
                preTriggerSampleCount,
                nominalVolts,
                sampleIntervalSeconds,
                settings);

            result.PacketCount = packets.Count;
            result.ExpectedPacketCount = settings.ExpectedAdvertisingPacketCount;
            result.PacketCountMatchesExpected =
                packets.Count == settings.ExpectedAdvertisingPacketCount;

            double[] packetDroops = new double[packets.Count];
            int[] packetStarts = new int[packets.Count];
            int[] packetEnds = new int[packets.Count];
            double peakDroopMillivolts = 0;
            for (int packetIndex = 0; packetIndex < packets.Count; packetIndex++)
            {
                PacketDip packet = packets[packetIndex];
                packetDroops[packetIndex] = packet.DroopMillivolts;
                packetStarts[packetIndex] = packet.StartIndex;
                packetEnds[packetIndex] = packet.EndIndex;
                if (packet.DroopMillivolts > peakDroopMillivolts)
                {
                    peakDroopMillivolts = packet.DroopMillivolts;
                }
            }

            // If packet detection found nothing (threshold too high / noise), fall
            // back to the whole post-trigger minimum so the trial still has a droop.
            if (packets.Count == 0)
            {
                int minimumSampleIndex = preTriggerSampleCount;
                double minimumVolts = voltageSamples[preTriggerSampleCount];
                for (int sampleIndex = preTriggerSampleCount + 1; sampleIndex < voltageSamples.Length; sampleIndex++)
                {
                    if (voltageSamples[sampleIndex] < minimumVolts)
                    {
                        minimumVolts = voltageSamples[sampleIndex];
                        minimumSampleIndex = sampleIndex;
                    }
                }
                peakDroopMillivolts = (nominalVolts - minimumVolts) * 1000.0;
                packetStarts = new int[] { minimumSampleIndex };
                packetEnds = new int[] { minimumSampleIndex };
            }

            result.PacketDroopMillivolts = packetDroops;
            result.PacketStartIndices = packetStarts;
            result.PacketEndIndices = packetEnds;
            result.DroopMillivolts = peakDroopMillivolts;
            result.PassedDroopSpec = result.DroopMillivolts <= settings.DroopSpecLimitMillivolts;

            double[] rebounds = MeasureInterPacketRebounds(
                voltageSamples,
                packets,
                nominalVolts);
            result.InterPacketReboundPercent = rebounds;
            if (rebounds.Length > 0)
            {
                double reboundSum = 0;
                for (int reboundIndex = 0; reboundIndex < rebounds.Length; reboundIndex++)
                {
                    reboundSum = reboundSum + rebounds[reboundIndex];
                }
                result.MeanInterPacketReboundPercent = reboundSum / rebounds.Length;
            }

            // Burst-active width: first ADV_IND edge to last ADV_IND exit. Always
            // defined when packets were found — does not depend on post-burst room.
            if (packets.Count > 0)
            {
                result.BurstActiveMicroseconds =
                    (packets[packets.Count - 1].EndIndex - packets[0].StartIndex)
                    * sampleIntervalSeconds * 1e6;
            }

            // Post-burst recovery: clock from last ADV_IND exit. Prefer "climbed
            // RecoveryPercentOfPeakDroop of the peak dip" over a tight absolute
            // band around the pre-trigger AC baseline (AC pedestals fail that).
            int settleSearchFrom = preTriggerSampleCount;
            if (packets.Count > 0)
            {
                settleSearchFrom = packets[packets.Count - 1].EndIndex;
            }

            double recoveryThresholdMillivolts;
            if (settings.RecoveryPercentOfPeakDroop > 0 && peakDroopMillivolts > 0)
            {
                recoveryThresholdMillivolts =
                    peakDroopMillivolts * (1.0 - settings.RecoveryPercentOfPeakDroop);
            }
            else
            {
                recoveryThresholdMillivolts = settings.SettlingBandMillivolts;
            }

            double holdTimeSeconds = settings.SettlingHoldTimeMicroseconds * 1e-6;
            int holdSampleCount = (int)Math.Ceiling(holdTimeSeconds / sampleIntervalSeconds);
            if (holdSampleCount < 1)
            {
                holdSampleCount = 1;
            }

            int recoverySampleIndex = FindRecoveredHold(
                voltageSamples,
                settleSearchFrom,
                nominalVolts,
                recoveryThresholdMillivolts,
                holdSampleCount);

            if (recoverySampleIndex < 0)
            {
                result.DidSettle = false;
                result.SettleTimeMicroseconds = 0;
                result.BurstDurationMicroseconds = 0;
            }
            else
            {
                result.DidSettle = true;
                result.SettleTimeMicroseconds =
                    (recoverySampleIndex - settleSearchFrom) * sampleIntervalSeconds * 1e6;

                int burstStart = packets.Count > 0
                    ? packets[0].StartIndex
                    : preTriggerSampleCount;
                result.BurstDurationMicroseconds =
                    (recoverySampleIndex - burstStart) * sampleIntervalSeconds * 1e6;
            }

            return result;
        }

        private static List<PacketDip> FindPacketDips(
            double[] voltageSamples,
            int preTriggerSampleCount,
            double nominalVolts,
            double sampleIntervalSeconds,
            DroopMeasurementSettings settings)
        {
            double enterVolts = nominalVolts - (settings.PacketDetectMillivolts / 1000.0);
            // Exit halfway back toward the baseline so brief inter-packet spikes
            // that do not reach nominal still end the current packet.
            double exitVolts = nominalVolts - (settings.PacketDetectMillivolts * 0.5 / 1000.0);

            int minimumPacketSamples = (int)Math.Ceiling(
                settings.MinimumPacketWidthMicroseconds * 1e-6 / sampleIntervalSeconds);
            if (minimumPacketSamples < 1)
            {
                minimumPacketSamples = 1;
            }

            List<PacketDip> packets = new List<PacketDip>();
            bool inPacket = false;
            int startIndex = -1;
            int minimumIndex = -1;
            double minimumVolts = 0;

            for (int sampleIndex = preTriggerSampleCount; sampleIndex < voltageSamples.Length; sampleIndex++)
            {
                double sampleVolts = voltageSamples[sampleIndex];
                if (!inPacket)
                {
                    if (sampleVolts < enterVolts)
                    {
                        inPacket = true;
                        startIndex = sampleIndex;
                        minimumIndex = sampleIndex;
                        minimumVolts = sampleVolts;
                    }
                }
                else
                {
                    if (sampleVolts < minimumVolts)
                    {
                        minimumVolts = sampleVolts;
                        minimumIndex = sampleIndex;
                    }

                    if (sampleVolts > exitVolts)
                    {
                        int endIndex = sampleIndex;
                        int width = endIndex - startIndex;
                        if (width >= minimumPacketSamples)
                        {
                            PacketDip packet = new PacketDip();
                            packet.StartIndex = startIndex;
                            packet.EndIndex = endIndex;
                            packet.MinimumIndex = minimumIndex;
                            packet.DroopMillivolts = (nominalVolts - minimumVolts) * 1000.0;
                            packets.Add(packet);
                        }

                        inPacket = false;
                    }
                }
            }

            if (inPacket)
            {
                int endIndex = voltageSamples.Length - 1;
                int width = endIndex - startIndex;
                if (width >= minimumPacketSamples)
                {
                    PacketDip packet = new PacketDip();
                    packet.StartIndex = startIndex;
                    packet.EndIndex = endIndex;
                    packet.MinimumIndex = minimumIndex;
                    packet.DroopMillivolts = (nominalVolts - minimumVolts) * 1000.0;
                    packets.Add(packet);
                }
            }

            return packets;
        }

        private static double[] MeasureInterPacketRebounds(
            double[] voltageSamples,
            List<PacketDip> packets,
            double nominalVolts)
        {
            if (packets.Count < 2)
            {
                return new double[0];
            }

            double[] rebounds = new double[packets.Count - 1];
            for (int gapIndex = 0; gapIndex < packets.Count - 1; gapIndex++)
            {
                PacketDip left = packets[gapIndex];
                PacketDip right = packets[gapIndex + 1];
                double peakVolts = voltageSamples[left.EndIndex];
                for (int sampleIndex = left.EndIndex; sampleIndex <= right.StartIndex; sampleIndex++)
                {
                    if (voltageSamples[sampleIndex] > peakVolts)
                    {
                        peakVolts = voltageSamples[sampleIndex];
                    }
                }

                double packetFloorVolts = nominalVolts - (left.DroopMillivolts / 1000.0);
                double recoverableVolts = nominalVolts - packetFloorVolts;
                if (recoverableVolts <= 0)
                {
                    rebounds[gapIndex] = 0;
                }
                else
                {
                    double climbedVolts = peakVolts - packetFloorVolts;
                    if (climbedVolts < 0)
                    {
                        climbedVolts = 0;
                    }
                    rebounds[gapIndex] = (climbedVolts / recoverableVolts) * 100.0;
                }
            }

            return rebounds;
        }

        /// <summary>
        /// One-sided recovery: sample is recovered when it is no more than
        /// thresholdMillivolts below the quiet baseline (positive overshoot is fine).
        /// </summary>
        private static int FindRecoveredHold(
            double[] voltageSamples,
            int searchFromIndex,
            double nominalVolts,
            double thresholdMillivolts,
            int holdSampleCount)
        {
            int lastWindowStart = voltageSamples.Length - holdSampleCount;
            if (searchFromIndex > lastWindowStart)
            {
                return -1;
            }

            double floorVolts = nominalVolts - (thresholdMillivolts / 1000.0);
            for (int windowStart = searchFromIndex; windowStart <= lastWindowStart; windowStart++)
            {
                bool entireWindowRecovered = true;
                for (int offset = 0; offset < holdSampleCount; offset++)
                {
                    if (voltageSamples[windowStart + offset] < floorVolts)
                    {
                        entireWindowRecovered = false;
                        break;
                    }
                }

                if (entireWindowRecovered)
                {
                    return windowStart;
                }
            }

            return -1;
        }
    }
}
