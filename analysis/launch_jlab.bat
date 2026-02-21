@echo off
setlocal

REM ---- EDIT THESE ----
set ENV_NAME=bodaqs
set WORKDIR=D:\Dev\BODAQS\analysis
REM --------------------

REM Find conda (works for most Anaconda/Miniconda installs)
set "CONDA_BAT=%USERPROFILE%\miniconda3\condabin\conda.bat"
if not exist "%CONDA_BAT%" set "CONDA_BAT=%USERPROFILE%\anaconda3\condabin\conda.bat"

if not exist "%CONDA_BAT%" (
  echo Could not find conda.bat.
  echo Edit CONDA_BAT in this script to point at your install.
  pause
  exit /b 1
)

REM Load conda into this shell, activate env, cd, launch JupyterLab
call "%CONDA_BAT%" activate "%ENV_NAME%"
if errorlevel 1 (
  echo Failed to activate conda env: %ENV_NAME%
  pause
  exit /b 1
)

cd /d "%WORKDIR%"
jupyter lab

endlocal
