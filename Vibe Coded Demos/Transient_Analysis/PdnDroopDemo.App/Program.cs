using System;
using System.Windows.Forms;

namespace PdnDroopDemo
{
    /// <summary>Starts the live droop window. The measurement itself is in PdnDroopDemo.Core.</summary>
    internal static class Program
    {
        [STAThread]
        private static void Main()
        {
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Application.Run(new MainForm());
        }
    }
}
