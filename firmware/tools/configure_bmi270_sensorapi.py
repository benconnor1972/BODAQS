"""Constrain Bosch's SensorAPI package to the BMI270 driver sources.

The upstream repository does not provide PlatformIO metadata. PlatformIO's
legacy library builder therefore discovers C files in the example trees as
library sources, even though those examples depend on hardware-specific
``common.h`` and magnetometer drivers that are not part of BODAQS.

The dependency remains pinned and downloaded by PlatformIO. This pre-build
step supplies package-local metadata in the generated ``.pio`` directory so
only the two official sources needed by the BMI270 integration are compiled.
"""

Import("env")

import json
from pathlib import Path


package_dir = (
    Path(env.subst("$PROJECT_LIBDEPS_DIR"))
    / env.subst("$PIOENV")
    / "BMI270_SensorAPI"
)
manifest_path = package_dir / "library.json"

manifest = {
    "name": "BMI270_SensorAPI",
    "version": "2.86.1+bodaqs.1",
    "build": {
        "srcFilter": [
            "+<bmi2.c>",
            "+<bmi270.c>",
        ]
    },
}
manifest_text = json.dumps(manifest, indent=2) + "\n"

if package_dir.is_dir():
    if not manifest_path.exists() or manifest_path.read_text() != manifest_text:
        manifest_path.write_text(manifest_text)
