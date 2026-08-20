$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = New-Object System.Text.UTF8Encoding $false
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
Add-Type -AssemblyName System.Speech
$culture = New-Object System.Globalization.CultureInfo 'zh-CN'
$eng = New-Object System.Speech.Recognition.SpeechRecognitionEngine $culture
$choices = New-Object System.Speech.Recognition.Choices
$phrases = @('你好','你好啊','你好呀','嗨','喂','哈喽','hello','hi','lulu','LuLu','噜噜','露露','璐璐')
foreach ($p in $phrases) { [void]$choices.Add($p) }
$gb = New-Object System.Speech.Recognition.GrammarBuilder
$gb.Culture = $culture
$gb.Append($choices)
$wake = New-Object System.Speech.Recognition.Grammar $gb
$wake.Name = 'wake'
$listen = New-Object System.Speech.Recognition.DictationGrammar
$listen.Name = 'listen'
$eng.LoadGrammar($wake)
$eng.InitialSilenceTimeout = [TimeSpan]::FromSeconds(0.15)
$eng.BabbleTimeout = [TimeSpan]::FromSeconds(0.4)
$eng.EndSilenceTimeout = [TimeSpan]::FromSeconds(0.35)
$loadedListen = $false
[Console]::Out.WriteLine('READY')
[Console]::Out.Flush()
while ($true) {
  $line = [Console]::In.ReadLine()
  if ($null -eq $line) { break }
  if ($line -eq 'quit') { break }
  $parts = $line.Split('|', 2)
  $mode = $parts[0]
  $path = $parts[1]
  if ($mode -eq 'listen') {
    if (-not $loadedListen) { $eng.LoadGrammar($listen); $loadedListen = $true }
  } elseif ($loadedListen) {
    $eng.UnloadGrammar($listen)
    $loadedListen = $false
  }
  try {
    $eng.SetInputToWaveFile($path)
    $result = $eng.Recognize([TimeSpan]::FromSeconds(4))
    if ($result -and $result.Text) {
      [Console]::Out.WriteLine($result.Text)
    } else {
      [Console]::Out.WriteLine('')
    }
  } catch {
    [Console]::Out.WriteLine('')
  }
  [Console]::Out.Flush()
}
$eng.Dispose()
