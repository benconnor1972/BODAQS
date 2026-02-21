# BODAQS

### Bicycle Open Data Acquisition System

BODAQS is a project focused on making mountain-bike data acquisition and analysis accessible — allowing the curious to explore and learn, and the driven a new tool to chase performance.

The project provides **open designs** for the hardware, firmware, analysis tools, and mechanical parts needed to collect and analyse mountain-bike data. It follows a build-it-yourself ethos, emphasising simplicity and low cost **without compromising functionality**.

Data acquisition is ubiquitous in motorsport, and increasingly common at the top end of gravity mountain-bike racing. Tools like SRAM’s ShockWiz offer an elegant solution for many users — but for the engineering-minded or budget-constrained, the choice is often between high cost with full functionality, or limited access to the underlying data.

BODAQS aims to offer an alternative: hardware that can be built with basic soldering skills using widely available parts; firmware with deep functionality and a structure designed for long-term expansion; and data analysis built on powerful, free tools — alongside mounting and mechanical designs that can be 3D printed at home or produced at low cost.

Follow along as we iterate the hardware, firmware and analysis and share our results.

## Hardware
The brains of the BODAQS logger is a Sparkfun ESP32 Thing Plus S3 development board, which is available at low cost worldwide. Additional circuitry to ensure sensor inputs are clean and noise-free can be built on stripboard (available from electronics hobby shops) or on a small custom PCB (available from Asian suppliers at astonishingly low cost). Designs and bills of materials are provided for both options and either can be assembled by someone who has (or who is prepared to learn) basic soldering skills.

Sensors are plugged in to one or more of the four analog input connectors, or via an I2C digital connection. The logger also features a small OLED screen and 5-way navigation pad for changing settings, and can support an optional handlebar-mounted switch to start and stop logging and mark events of interest in the log. 

## Firmware
The code that runs on the logger handles a wide array of tasks, and is designed with expansion in mind. Some of the key firmware modules include:

 - Logging: the logger samples its sensors and records the results to SD card at rates up to 500Hz (500 times per second). Log files are written in human-readable CSV format.  
 - Configuration management: configuration settings including sensor setup, wifi settings and user preferences are stored in a human-readable configuration file on the SD card
 - Calibration: basic sensor calibration can be done on the logger - for analog inputs, setting the full range and zero point are supported. Calibration parameters are stored on the SD card.
 - Web access: users can connect to the logger via wifi and download (or upload) files or configure the device.
 - Data transformation: users can specify tranformation functions for logger outputs, for example to report measured shock movement as wheel movement. Transformation functions can be specified as polynomials or look-up tables and are stored per-sensor on the SD card.

## Analysis
Sampling and recording sensor data is simply an engineering problem. Interpreting the data to find meaning is categorically different. Anyone who has attempted to browse a large, dense dataset in a spreadsheet will attest that the conclusions do not write themselves.

The specifics of how one interprets data depend on the intended task. How then should analysis of suspension data be done? If the objective is to "make my suspension not suck", then you might build analysis tools that detect bad things happening and suggest what to do about them based on a general understanding of the physics of suspension. But the more specific and detailed the objective becomes, the less likely it is that general-purpose analysis will reveal the answers sought.

The BODAQS project walks the line between a black-box 'suspension wizard' and simply dumping raw data on the user. It provides a transparent set of analysis tools on a free and open-source platform, with the raw and derived datasets delivered in standard (and documented) form so that, if users are so inclined, they can extend the analysis however they choose.

Features of the BODAQS analysis framework include:
 - Python-based toolset: the analytical heavy lifting is done using Python, a widely-used programming language well suited to data analysis. But while users with the relevant knowledge (or willingness to learn) can modify and extend the tools, it shouldn't be necessary to do so: the point of an open-source project is to allow users to leverage the work of the community.
 - Runs in Jupyter Lab: Jupyter Lab is a free and open-source interactive computing environment ideally suited to making large datasets accessible and visible. Regular users can use the tools as-is; power users can modify and develop them as they see fit.
 - Batch pre-processing pipeline: automated tools to ingest, validate, transform and parse data logger files. Pre-processed data is formatted to allow rapid access and can be stored in any convenient location.
 - Automated event detection: a key pre-processing step is detection of interesting events. A sophisticated event-description schema allows users to specify exactly what they want in a human-readable text file; the pre-processing pipeline will automatically identify and catalog occurrences of those events, capture a slice of the surrounding data and calculate metrics the user specifies  for each event.
 - Session, event and metric browsing tools: a range of general-purpose visualisation widgets for examining the data, including session and event browsers and histogram and scatter charts that can be used to characterise and compare sensor outputs. 