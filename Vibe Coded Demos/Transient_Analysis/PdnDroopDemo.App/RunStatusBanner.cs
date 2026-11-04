using System;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Windows.Forms;

namespace PdnDroopDemo
{
    /// <summary>
    /// Top-of-form status: one fixed LED chip with centered caption.
    /// Blinking yellow "Setting up", solid green "Running", solid blue "Ready".
    /// Blue for idle/ready is the usual contrast to green-active (yellow stays caution/setup).
    /// </summary>
    public class RunStatusBanner : Panel
    {
        // Match the Run button footprint (90×28) so the status chip stays visible
        // without dominating the plots below.
        private const int LedWidth = 100;
        private const int LedHeight = 28;
        private const int CornerRadius = 6;

        private readonly System.Windows.Forms.Timer _blinkTimer;
        private MeasurementPhase _phase = MeasurementPhase.Ready;
        private bool _blinkOn = true;

        private static readonly Color ReadyBlue = Color.FromArgb(45, 125, 220);
        private static readonly Color RunningGreen = Color.FromArgb(40, 180, 75);
        private static readonly Color SettingUpYellowBright = Color.FromArgb(240, 195, 35);
        private static readonly Color SettingUpYellowDim = Color.FromArgb(140, 110, 20);
        private static readonly Color BannerBack = Color.FromArgb(28, 32, 40);
        private static readonly Color TextOnYellow = Color.FromArgb(28, 28, 28);
        private static readonly Color TextOnLit = Color.White;

        public RunStatusBanner()
        {
            Height = LedHeight + 16;
            Dock = DockStyle.Top;
            BackColor = BannerBack;
            DoubleBuffered = true;

            _blinkTimer = new System.Windows.Forms.Timer();
            // Was 400 ms; ×1.5 slows On→Off→On so the blink reads clearly from across the bench.
            _blinkTimer.Interval = 600;
            _blinkTimer.Tick += OnBlinkTick;

            SetPhase(MeasurementPhase.Ready);
        }

        public void SetPhase(MeasurementPhase phase)
        {
            if (InvokeRequired)
            {
                BeginInvoke(new Action(() => SetPhase(phase)));
                return;
            }

            _phase = phase;
            _blinkOn = true;
            if (phase == MeasurementPhase.SettingUp)
            {
                if (!_blinkTimer.Enabled)
                {
                    _blinkTimer.Start();
                }
            }
            else
            {
                _blinkTimer.Stop();
            }

            Invalidate();
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing)
            {
                _blinkTimer.Stop();
                _blinkTimer.Dispose();
            }
            base.Dispose(disposing);
        }

        private void OnBlinkTick(object sender, EventArgs args)
        {
            _blinkOn = !_blinkOn;
            Invalidate();
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            base.OnPaint(e);

            Graphics g = e.Graphics;
            g.SmoothingMode = SmoothingMode.AntiAlias;
            g.TextRenderingHint = System.Drawing.Text.TextRenderingHint.ClearTypeGridFit;
            g.Clear(BannerBack);

            string caption;
            Color ledColor;
            Color textColor;
            switch (_phase)
            {
                case MeasurementPhase.SettingUp:
                    caption = "Setting up";
                    ledColor = _blinkOn ? SettingUpYellowBright : SettingUpYellowDim;
                    textColor = TextOnYellow;
                    break;
                case MeasurementPhase.Running:
                    caption = "Running";
                    ledColor = RunningGreen;
                    textColor = TextOnLit;
                    break;
                default:
                    caption = "Ready";
                    ledColor = ReadyBlue;
                    textColor = TextOnLit;
                    break;
            }

            int ledLeft = (Width - LedWidth) / 2;
            int ledTop = (Height - LedHeight) / 2;
            Rectangle ledBounds = new Rectangle(ledLeft, ledTop, LedWidth, LedHeight);

            using (GraphicsPath path = RoundedRect(ledBounds, CornerRadius))
            {
                using (SolidBrush shadow = new SolidBrush(Color.FromArgb(50, 0, 0, 0)))
                {
                    Rectangle shadowBounds = ledBounds;
                    shadowBounds.Offset(1, 2);
                    using (GraphicsPath shadowPath = RoundedRect(shadowBounds, CornerRadius))
                    {
                        g.FillPath(shadow, shadowPath);
                    }
                }

                using (SolidBrush fill = new SolidBrush(ledColor))
                {
                    g.FillPath(fill, path);
                }

                using (Pen rim = new Pen(Color.FromArgb(80, 255, 255, 255), 1f))
                {
                    g.DrawPath(rim, path);
                }
            }

            using (Font font = new Font("Segoe UI", 9, FontStyle.Bold))
            using (SolidBrush textBrush = new SolidBrush(textColor))
            using (StringFormat format = new StringFormat())
            {
                format.Alignment = StringAlignment.Center;
                format.LineAlignment = StringAlignment.Center;
                g.DrawString(caption, font, textBrush, ledBounds, format);
            }
        }

        private static GraphicsPath RoundedRect(Rectangle bounds, int radius)
        {
            int diameter = radius * 2;
            GraphicsPath path = new GraphicsPath();
            path.AddArc(bounds.Left, bounds.Top, diameter, diameter, 180, 90);
            path.AddArc(bounds.Right - diameter, bounds.Top, diameter, diameter, 270, 90);
            path.AddArc(bounds.Right - diameter, bounds.Bottom - diameter, diameter, diameter, 0, 90);
            path.AddArc(bounds.Left, bounds.Bottom - diameter, diameter, diameter, 90, 90);
            path.CloseFigure();
            return path;
        }
    }
}
