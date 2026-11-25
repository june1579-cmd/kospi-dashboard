' Starts collector.py with no window (pythonw). Called by Task Scheduler every 10 minutes.
' collector.py exits immediately if another copy is already running.
Set fso = CreateObject("Scripting.FileSystemObject")
d = fso.GetParentFolderName(WScript.ScriptFullName)
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = d
If fso.FileExists(d & "\.venv\Scripts\pythonw.exe") Then
  sh.Run """" & d & "\.venv\Scripts\pythonw.exe"" """ & d & "\collector.py""", 0, False
End If
