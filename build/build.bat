@echo off
rem Build the C++ shell (WebView2). Called by build_window.py or manually.
setlocal
set "VS=C:\Program Files\Microsoft Visual Studio\18\Community"
if not exist "%VS%\VC\Auxiliary\Build\vcvars64.bat" (
  echo [ERROR] vcvars64.bat not found. Edit VS path in build.bat.
  exit /b 2
)
call "%VS%\VC\Auxiliary\Build\vcvars64.bat" >nul
if errorlevel 1 (
  echo [ERROR] vcvars64 failed.
  exit /b 2
)
set "SDK=%~dp0sdk\build\native"
if not exist "%SDK%\include\WebView2.h" (
  echo [ERROR] WebView2 SDK missing: %SDK%
  exit /b 2
)
pushd "%~dp0"
cl /nologo /std:c++17 /EHsc /O2 /MD /utf-8 launcher.cpp ^
  /I"%SDK%\include" ^
  /link /SUBSYSTEM:WINDOWS /OUT:"af-score.exe" ^
  "%SDK%\x64\WebView2LoaderStatic.lib" ^
  wininet.lib ws2_32.lib ole32.lib oleaut32.lib user32.lib shell32.lib gdi32.lib advapi32.lib
set "RC=%ERRORLEVEL%"
popd
if not "%RC%"=="0" (
  echo [ERROR] compile failed, code %RC%
  exit /b %RC%
)
echo [OK] af-score.exe built.
exit /b 0
