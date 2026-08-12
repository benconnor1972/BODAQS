---
title: Meet the BODAQS A8
description: A practical overview of what it is like to own, configure, ride with, and use a BODAQS A8 data logger.
---

The BODAQS A8 is a small, self-contained data logger that lives on the bike and records what the bike is doing while you ride. You mount the 3D-printed enclosure to the downtube, connect the sensors that matter to you, insert a MicroSD card, and use the display and keypad on the lid to control it. It is intended to feel like a piece of riding equipment rather than a bench-top electronics project, while remaining open enough to repair, adapt, and understand.

Owning an A8 is less about collecting every possible channel and more about choosing a question. A simple installation might use linear potentiometers to record fork and shock movement. A bike whose rear suspension is difficult to measure directly might instead use a rotary angle sensor on the linkage. The logger currently supports analogue displacement sensors, AS5600 and AS5048B angle sensors, BODAQS string-pot sensors, and an external GPS for position, speed, and heading. There is room to expand a setup over time: the two analogue connections provide up to eight analogue channels, while digital sensor connections cover I2C devices and GPS.

That flexibility does mean the A8 is not a universal plug-and-play sensor box. Sensors need to be wired, described in the logger configuration, and calibrated so that a voltage or encoder count becomes a useful measurement such as millimetres of travel or degrees of rotation. The external connectors use the same rugged six-pin M8 format but perform different jobs, so a little care—and sensible colour coding—helps prevent the wrong lead being connected in the wrong place. The [sensor guide](/sensor-connection-and-wiring-guide/) takes you through those choices and the practical setup.

## At the trailhead

Once the system is configured, normal operation is deliberately simple. The OLED status screen shows the essentials at a glance: whether the logger is ready, how many sensor channels are active, the selected sample rate, battery level, SD-card state, time, and GPS status when a GPS is fitted. The physical keypad lets you start or stop a recording, change common settings, calibrate supported sensors, check the health of the logger, and use live sensor readings when setting sag.

An optional handlebar switch makes the controls accessible while riding. It can start or stop logging, mark a feature or test section in the data, or perform another configured action, while its LED can confirm that recording is active. That means a typical run does not involve taking out a phone: switch the logger on, check the status screen, start the recording, and ride. Event marks made on the trail are preserved in the log and can later help you find the exact rock garden, corner, or setup test you wanted to examine.

The logger can be configured to sample at rates up to **1000 Hz**, but that figure is a theoretical ceiling rather than a promise that every connected sensor will produce a thousand useful readings per second. Sensor choice matters. Some analogue installations can take advantage of high rates, while GPS and other asynchronous or digital sensors operate at their own lower update rates. Sensors sharing an analogue converter may also share its total capacity. In practice, you select a rate that suits the sensors and the question you are asking; the logger reports its effective rate so you can see what it actually achieved.

## Configuration without a special app

For work that would be awkward on a small display, the A8 provides its own local web interface. It can join a known Wi-Fi network or create an access point of its own, allowing a phone, tablet, or computer to connect directly. From a browser you can configure sensors, calibration and logging behaviour, manage the files on the MicroSD card, and inspect the logger's settings without installing a dedicated mobile app.

Wi-Fi is kept separate from active logging so that recording gets the logger's full attention. When a ride is finished, you can remove the SD card, download files through the web interface, or place the logger into its deliberate upload mode and let the BODAQS Import Manager collect completed sessions. The separation is visible on the display, so it is clear whether the unit is ready to record or waiting in file-transfer mode. The [user guide](/user-guide/) describes the everyday controls and transfer options in detail.

## From a ride to something useful

The logger is one part of the BODAQS workflow. The Import Manager organises recordings into a library and prepares the raw sensor data for analysis. That preparation can apply calibrations and suspension-linkage transformations, calculate displacement and velocity, preserve setup notes, and associate GPS information with the ride. From there, the data can be explored in BODAQS Analysis, exported for use with data.syn.bike, or examined more directly through the Python and Jupyter tools intended for advanced users.

This software is still developing, but the data is not held hostage by it. Logs live on your own SD card, the formats and processing tools are open, and you can inspect or reuse the files outside the standard workflow. The hosted [BODAQS software demo](https://demo.bodaqs.net/) gives a useful sense of how sessions can be organised, compared, and turned into suspension plots and ride-level results.

## The physical reality

The A8 combines a custom circuit board, internal lithium-polymer battery, MicroSD storage, OLED display, membrane controls, metal sensor connectors, and a bike-specific mount inside a 3D-printed enclosure. The case can be opened with ordinary tools, the battery and display are commodity parts, and the enclosure components can be printed again if they are damaged or if the design evolves. This serviceability is a large part of the point: the logger is something you can maintain rather than a sealed product that becomes waste when one part fails.

It is also important to set the right expectation. The A8 is a carefully designed DIY instrument, not a factory-sealed consumer appliance. Its resistance to dirt and water depends partly on print quality, assembly, sealing, connector caps, and cable routing. Building and installing it asks for patience, basic soldering and mechanical confidence, and a willingness to follow the guides. In return, you get a logger whose behaviour is visible, whose parts are documented, and whose purpose can grow with your curiosity.

If you want a completely turn-key product, the A8 may not be the right fit. If you like the idea of owning the measurement process—from the sensor on the bike to the plot on the screen—it is designed for exactly that experience. You can [build one from the published designs](/logger-build-guide/bodaqs-a8/sourcing-hardware/) or [buy a PCB or kit](/buy-pcb-or-kit/) to reduce the parts-sourcing work.
