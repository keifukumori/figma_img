'" Launch Windows .bat without showing a console window
Set WshShell = CreateObject("WScript.Shell")
WshShell.Run "scripts\run_figma.bat", 0, True
