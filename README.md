# BODAQS

### Bicycle Open Data Acquisition System

BODAQS is a project focused on making mountain-bike data acquisition and analysis accessible — allowing the curious to explore and learn, and the driven a new tool to chase performance.

The project provides **open designs** for the hardware, software, analysis tools, and mechanical parts needed to collect and analyze mountain-bike data. It follows a build-it-yourself ethos, emphasising simplicity and low cost **without compromising functionality**.

Data acquisition is ubiquitous in motorsport, and it's becoming more common at the sharp end of gravity mountain-bike racing too. But for the engineering-minded (or budget-constrained), the choice is often between costly professional systems or consumer tools that keep the underlying data hidden.

BODAQS aims to offer an alternative: hardware that can be built with basic soldering skills using widely available parts; software with deep functionality and a structure designed for long-term expansion; and analysis built on powerful, free tools — alongside mounting and mechanical designs that can be 3D printed at home or produced at low cost.

Follow along as we iterate the hardware, software and analysis and share our results.

## The device

At the centre of BODAQS is a small logger you can mount on a bike to record what your suspension (and other sensors) are doing during a ride.

It’s designed to be modular: you can start simple and add capability over time.

The logger records at a high maximum **sample rate** (how many measurements it takes each second), so it can capture rapid events like fast suspension movement in fine detail.

A small screen and buttons make it usable on the bike, and an optional handlebar-mounted button lets you tag moments of interest (for example: a hard landing) so they’re easy to find later.

Settings live on the device in a simple text configuration file. The device can connect to wifi to allow settings to be edited or log files downloaded using any device with a web browser.

Logs are saved as plain text tables, so you can open them with common tools and keep your data portable.

## Analysis

Sampling and recording sensor data is an engineering problem; deciding what it *means* is the hard part. Anyone who has stared at a large time-series dataset in a spreadsheet knows the conclusions do not write themselves.

Interpretation depends on your question: you might be trying to tune for a specific outcome or just to get within the wide window of "good enough" — and different questions call for different ways of looking at the same ride.

BODAQS aims to sit between a black-box “just trust the result” tool and a blank page. The goal isn’t to provide instant answers for everyone, but to provide a guided, transparent framework that supports ambition and curiosity helps you build real understanding.

The analysis tooling is built in **Python** (a widely used language for data work), and is designed so you can use it as-is, adapt it to your own questions, and share improvements back with the community.

Features of the BODAQS analysis framework include:
- A pre-processing pipeline to clean, validate, and organise logs into consistent, comparable sessions.
- Automated detection of “events” (such as jump landings, rebounds from a deep compression, or other patterns you define) so you can fish the moments that matter from the sea of data.
- Tools to browse sessions, events, and metrics — and to compare rides, setups, or components in a repeatable way.

## Ethos and inspiration

This project exists for many reasons but three specific precursors stand out:
 - ShockWiz: Nigel Wade's ground-breaking product, now owned by SRAM, is in a category of one: mountain bike suspension analysis products that can be set up by an average user in under 20 minutes and provide useful feedback to the vast majority of riders. I was a happy ShockWiz user for many years and probably still would be if I hadn't discovered coil suspension. An elegant product that extracts maximum insight from minimum hardware, with a simplicity that hides some very clever engineering.
 - Sufni: The first open-source mountain bike data acquisition project to cross my path. For a variety of reasons I decided to take a different path rather than build one, but it's an impressive piece of work and the use of Lego for sensor mounting deserves a credit of its own.
 - RepRap: The movement that gave birth to cheap and ubiquitous 3D printing wasn't driven by market analysis by some big corporation, but by people who wanted a thing they couldn't buy (at a reasonable price). The community development and sharing ethos persists although the 3D printer market is unrecognisable from 10 years ago.