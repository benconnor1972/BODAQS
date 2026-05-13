# BODAQS: Get Started with JupyterLab (Windows, no Conda)

This guide gets you from **"repo cloned"** to **"JupyterLab running your notebooks"** on **Windows**, assuming you **don't have Python installed yet** and you want a **single environment** using Python's built-in **venv**.

---

## 0) Prerequisites

You already have:
- A local clone of the **BODAQS** repo.

You will install:
- **Python** (includes `pip`)
- A **virtual environment** for this repo
- **JupyterLab**
- The repo's Python dependencies

---

## 1) Install Python on Windows

1. Download Python from the official site:
   - https://www.python.org/downloads/windows/

2. Run the installer and **make sure** you tick:
   - **Add python.exe to PATH**
   - (Optional but recommended) **Install launcher for all users**

3. Finish the install.

### Verify Python is installed

Open **PowerShell** and run:

```powershell
python --version
pip --version
```

You should see version output (for example `Python 3.12.x`).

If `python` is not found:
- Re-run the installer and ensure **"Add to PATH"** is checked, or
- Close and reopen PowerShell after installation.

---

## 2) Create a virtual environment inside the repo

In PowerShell, `cd` into your repo (adjust the path):

```powershell
cd D:\Dev\BODAQS
```

Create a virtual environment (named `.venv`):

```powershell
python -m venv .venv
```

Activate it:

```powershell
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks activation with an execution policy warning, run:

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

Then try activation again:

```powershell
.\.venv\Scripts\Activate.ps1
```

### Upgrade pip (recommended)

```powershell
python -m pip install --upgrade pip
```

---

## 3) Install BODAQS Python dependencies

BODAQS dependencies are defined in the repo-root `requirements.txt`.

From the repo root:

```powershell
python -m pip install -r requirements.txt
```

This is the canonical live environment specification, including JupyterLab.
Use it again after pulling dependency updates.

---

## 4) Launch JupyterLab

No separate `pip install jupyterlab` step is required after installing
`requirements.txt`.

From the **repo root** (recommended):

```powershell
python -m jupyter lab
```

A browser tab should open with the JupyterLab interface. If it does not,
PowerShell will print a local URL (usually starting with
`http://localhost:8888/lab`) that you can paste into your browser.

---

## 5) Open and run notebooks

In JupyterLab:
1. Use the left file browser to navigate to the notebook folder (commonly `notebooks/`, but it may differ).
2. Open a `.ipynb` file.
3. If prompted to select a kernel:
   - Choose the **Python** kernel associated with your `.venv`.

### Run a notebook

- Use **Run -> Run All Cells**, or press **Shift+Enter** to execute cell-by-cell.

---

## 6) Typical workflow (every time)

When you come back later:

1. Open PowerShell
2. Go to the repo
3. Activate the venv
4. Launch JupyterLab

```powershell
cd D:\Dev\BODAQS
.\.venv\Scripts\Activate.ps1
python -m jupyter lab
```

---

## Troubleshooting

### "ModuleNotFoundError: ..."

That package is not installed in your current environment. Confirm you activated the venv:

```powershell
where python
python -c "import sys; print(sys.executable)"
```

You should see a path inside `...\BODAQS\.venv\...`.

Then install dependencies again (Section 3).

---

### JupyterLab / notebook version conflict after a refresh

If `pip` reports that `notebook` requires a newer `jupyterlab`, refresh from
the repo-root `requirements.txt` again after pulling the latest branch changes:

```powershell
python -m pip install -r requirements.txt
python -m pip check
```

If warnings about invalid distributions such as `~upyterlab` persist, your venv
likely contains leftovers from an interrupted package upgrade. Recreating the
`.venv` is the cleanest fix.

---

### Jupyter launches but the kernel can't start / wrong kernel

Make sure `ipykernel` is installed in your venv:

```powershell
python -m pip install ipykernel
```

Then (optional) register a named kernel:

```powershell
python -m ipykernel install --user --name bodaqs --display-name "Python (BODAQS)"
```

Restart JupyterLab and select **Python (BODAQS)** as the kernel.

---

### Port already in use

Start JupyterLab on a different port:

```powershell
python -m jupyter lab --port 8889
```

---

### "jupyter is not recognized..."

You likely did not install JupyterLab in the active environment, or the venv is not activated.

Try:

```powershell
python -m pip install -r requirements.txt
python -m jupyter lab
```

---

## What I need from you (only if you want this guide to be repo-specific)

If you want this guide to mention *exact* file/folder names (for example the correct notebooks folder, the correct dependency install command, or a "first notebook to run"), tell me:
- What dependency file(s) your repo uses: `requirements.txt` / `pyproject.toml` / something else
- The folder where the notebooks live (for example `analysis/notebooks/`)
- The recommended "first notebook" (filename)

Then I can produce a tailored version with no conditionals.
