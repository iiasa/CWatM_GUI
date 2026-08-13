' Launch the CWatM GUI fully hidden (no console flash at all) using the project's
' virtual environment. Double-click this instead of gui.bat if you don't want to
' see even the brief cmd window that a .bat shows.
Option Explicit
Dim fso, shell, here, pyw, script
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
here = fso.GetParentFolderName(WScript.ScriptFullName)
pyw = here & "\venv\Scripts\pythonw.exe"
script = here & "\cwatm_gui.py"

If Not fso.FileExists(pyw) Then
    MsgBox "Virtual environment not found at:" & vbCrLf & pyw & vbCrLf & vbCrLf & _
           "Create it first:  python -m venv venv  then  venv\Scripts\pip install -r requirements.txt", _
           vbExclamation, "CWatM GUI"
    WScript.Quit 1
End If

shell.CurrentDirectory = here
' 0 = hidden window, False = don't wait for the GUI to exit.
shell.Run """" & pyw & """ """ & script & """", 0, False
