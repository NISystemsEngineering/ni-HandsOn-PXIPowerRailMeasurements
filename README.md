# PXI Power-Rail Monitoring: Hands-On Session

Everything needed to run the PXI power-rail monitoring hands-on session: the FAE setup manual, the
attendee exercises, presenter slides, the ESP32-C6 DUT firmware, the station flashing package, and the
Python and C# instructor demos.

The session shows how PXI instruments characterize a device's power rail. An SMU supplies and measures
the rail, a scope captures what the DUT draws and when, and an arb injects ripple onto the rail. The DUT
is an ESP32-C6-DevKitC-1-N8 running small firmware images that make BLE current bursts, rail droop and
brownout easy to see and repeat.

## Start here

| You want to... | Go to |
| --- | --- |
| Prepare and run a session (FAEs) | `docs/presenter/FAE_Setup_Manual.docx` |
| Give attendees their instructions | `docs/attendee/` |
| Present the session | `docs/presenter/` (slides) |
| Set up a customer station | Copy `PXI_Training` to `C:\` (see below) |
| Run the instructor demos | `Vibe Coded Demos/` (see below) |
| Change or rebuild firmware | `firmware/README.md` |

## Repo layout

```
docs/
  attendee/          Hands-on exercise document (customer-facing)
  presenter/         FAE setup manual and presenter slides (internal)
hardware/            Wiring diagram and setup photos
firmware/            ESP-IDF source projects for the DUT (see firmware/README.md)
PXI_Training/        Station package: copy to C:\PXI_Training
  1_Flash_and_Monitor_SLEEP.bat
  2_Flash_and_Monitor_BEACON.bat
  3_Flash_and_Monitor_BEACON_TRIGGERED.bat
  tools/             esptool.exe (tested version)
  waveform/          Arb ripple waveform used in Exercise 4
  exercises/         Prebuilt firmware images the batch files flash
Vibe Coded Demos/    Instructor-led automation demos
  Run_Demo_A_Brownout.bat
  Run_Demo_B_Droop.bat
  Brownout_Threshold/    Demo A source (Python)
  Transient_Analysis/    Demo B source (C#), with a prebuilt release/ folder
```

## Setting up a station

1. Clone this repo, or download it as a zip from the Code button. If you download a zip, unblock it before
   extracting (right-click the zip, **Properties**, **Unblock**), or Windows may warn about `esptool.exe`
   and the batch files.
2. Copy the `PXI_Training` folder to `C:\`, so the batch files are at `C:\PXI_Training`.
3. Follow Section 4 of the FAE setup manual: install the CP210x USB driver if needed, install
   `esp-idf-monitor`, and set the DUT's COM port in each batch file.

No ESP-IDF install or firmware build is needed to run the session.

## Running the instructor demos

Double-click a launcher in `Vibe Coded Demos`. Both work wherever the repo is cloned.

- **`Run_Demo_A_Brownout.bat`**: brownout threshold sweep (Python). Needs Python and the packages in
  `Brownout_Threshold/requirements.txt`.
- **`Run_Demo_B_Droop.bat`**: rail droop statistics (C#). Runs from the prebuilt `release` folder; no
  build needed.

Both demos need the DUT running the `beacon_triggered` image (`3_Flash_and_Monitor_BEACON_TRIGGERED.bat`).
They find the instruments and the DUT's COM port themselves, and InstrumentStudio does not need to be open.
See Section 9 of the FAE setup manual.

## Hardware

- PXIe chassis with at least 3 slots and a controller with a front-panel SMB TRIG connector
- 3 A-capable SMU (tested extensively on the PXIe-4147 only)
- 2-channel scope and an arbitrary waveform generator
- ESP32-C6-DevKitC-1-N8 DUT kit, wired as in Section 3 of the FAE setup manual; parts list in Section 2

## Videos

Session videos are hosted outside this repo. Links will be added here.

## Questions

Contact Charlie Knapp on Teams.
