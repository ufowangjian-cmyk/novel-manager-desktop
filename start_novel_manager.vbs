' 小说管理器启动脚本 v2.0
' 支持调试模式检测、自动等待服务启动、错误提示

Option Explicit

Dim WshShell, strPath, strPythonScript, configFile, appPort
Dim debugMode, fso, file, content

Set WshShell = CreateObject("WScript.Shell")
strPath = WshShell.CurrentDirectory
strPythonScript = strPath & "\novel-manager.py"
configFile = strPath & "\data\config.json"

' ===== 1. 检测调试模式（使用 JSON 解析）=====
debugMode = False
appPort = 5000

Set fso = CreateObject("Scripting.FileSystemObject")
If fso.FileExists(configFile) Then
    On Error Resume Next
    Set file = fso.OpenTextFile(configFile, 1)
    content = file.ReadAll
    file.Close
    
    ' 使用正则匹配 debug_mode 的值（更可靠）
    Dim regex
    Set regex = New RegExp
    regex.Pattern = """debug_mode""\s*:\s*(true|false)"
    regex.IgnoreCase = True
    regex.Global = False
    
    Dim matches
    Set matches = regex.Execute(content)
    If matches.Count > 0 Then
        debugMode = (LCase(matches(0).SubMatches(0)) = "true")
    End If

    ' 读取端口配置
    regex.Pattern = """app_port""\s*:\s*(\d+)"
    Set matches = regex.Execute(content)
    If matches.Count > 0 Then
        On Error Resume Next
        appPort = CInt(matches(0).SubMatches(0))
        If Err.Number <> 0 Then appPort = 5000
        On Error GoTo 0
    End If
    
    On Error GoTo 0
End If

' ===== 2. 检测 Python 是否存在 =====
Dim pythonCmd
pythonCmd = "python"
' 尝试 python3（Linux/macOS 兼容）
If Not CheckPython(pythonCmd) Then
    pythonCmd = "python3"
    If Not CheckPython(pythonCmd) Then
        MsgBox "❌ 未检测到 Python！" & vbCrLf & vbCrLf & _
               "请安装 Python 3.8 或更高版本" & vbCrLf & _
               "下载地址: https://www.python.org/downloads/", _
               vbCritical + vbOKOnly, "错误"
        WScript.Quit 1
    End If
End If

' ===== 3. 启动程序 =====
Dim runMode, cmdPrefix
If debugMode Then
    ' 调试模式：显示窗口
    runMode = 1  ' 正常显示窗口
    cmdPrefix = "cmd /k cd /d """ & strPath & """ && " & pythonCmd & " "
    MsgBox "🔧 调试模式已启用" & vbCrLf & vbCrLf & _
           "将显示命令行窗口，方便查看日志。" & vbCrLf & _
           "关闭命令行窗口即可停止程序。", _
           vbInformation + vbOKOnly, "调试模式"
Else
    ' 正常模式：隐藏窗口
    runMode = 0  ' 隐藏窗口
    cmdPrefix = "cmd /c cd /d """ & strPath & """ && " & pythonCmd & " "
End If

' 启动 Python
Dim objShell
Set objShell = CreateObject("WScript.Shell")
objShell.Run cmdPrefix & """" & strPythonScript & """", runMode, False

' ===== 4. 等待服务启动（带超时）=====
Dim maxRetries, retry, isReady, http
maxRetries = 30  ' 最多等待 30 秒
isReady = False

For retry = 1 To maxRetries
    WScript.Sleep 1000  ' 每秒检查一次
    
    ' 尝试连接服务
    On Error Resume Next
    Set http = CreateObject("MSXML2.ServerXMLHTTP.6.0")
    http.open "GET", "http://127.0.0.1:" & appPort, False
    http.send
    On Error GoTo 0
    
    If http.status = 200 Then
        isReady = True
        Exit For
    End If
Next

' ===== 5. 打开浏览器 =====
If isReady Then
    objShell.Run "http://127.0.0.1:" & appPort, 1, False
Else
    ' 即使服务没准备好，也尝试打开浏览器（可能端口不同）
    objShell.Run "http://127.0.0.1:" & appPort, 1, False
    MsgBox "⚠️ 服务启动超时" & vbCrLf & vbCrLf & _
           "请检查：" & vbCrLf & _
           "1. 小说目录是否存在" & vbCrLf & _
           "2. 端口 " & appPort & " 是否被占用" & vbCrLf & _
           "3. 查看日志文件: data\novel_manager.log", _
           vbExclamation + vbOKOnly, "提示"
End If

' ===== 辅助函数：检查 Python 是否存在 =====
Function CheckPython(cmd)
    On Error Resume Next
    Dim exec
    Set exec = WshShell.Exec(cmd & " --version")
    Do While exec.Status = 0
        WScript.Sleep 100
    Loop
    CheckPython = (exec.Status = 1)  ' 0=运行中, 1=完成
    On Error GoTo 0
End Function