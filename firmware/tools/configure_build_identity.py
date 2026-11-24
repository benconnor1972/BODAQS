"""PlatformIO hook. Emits a reproducible header and archived recipe per environment."""
Import("env")
import json
import sys
from pathlib import Path

root = Path(env.subst("$PROJECT_DIR"))
sys.path.insert(0, str(root / "tools"))
from build_identity import identity

options = dict(sorted(env.GetProjectOptions()))
recipe = identity(root, env.subst("$PIOENV"), options)
folder = Path(env.subst("$BUILD_DIR")) / "identity"
folder.mkdir(parents=True, exist_ok=True)
for name, text in {
    "BuildRecipe.h": '#pragma once\n#define BODAQS_BUILD_RECIPE_ID "' + recipe["id"] + '"\n',
    "build-recipe.json": json.dumps(recipe, indent=2, sort_keys=True) + "\n",
}.items():
    path = folder / name
    if not path.exists() or path.read_text(encoding="utf-8") != text:
        path.write_text(text, encoding="utf-8")
env.Append(CPPPATH=[str(folder)])
