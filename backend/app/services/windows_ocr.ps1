# TODO 33-2: read the Korean text in every PNG of a folder with Windows' built-in OCR (no install, no network).
# Writes [{frame, height, lines: [{text, y, h}]}] as UTF-8 JSON to -Out.
param([Parameter(Mandatory = $true)][string]$Dir, [Parameter(Mandatory = $true)][string]$Out)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Globalization.Language, Windows.Foundation, ContentType = WindowsRuntime]
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
        $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op, [Type]$type) { $task = $asTask.MakeGenericMethod($type).Invoke($null, @($op)); $task.Wait(); $task.Result }

$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage([Windows.Globalization.Language]::new('ko'))
if ($null -eq $engine) { Write-Error 'OCR_NO_KOREAN'; exit 3 }

$frames = New-Object System.Collections.Generic.List[object]
Get-ChildItem -LiteralPath $Dir -Filter *.png | Sort-Object Name | ForEach-Object {
    $file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($_.FullName)) ([Windows.Storage.StorageFile])
    $stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
    try {
        $decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
        $bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
        $result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
        $lines = @($result.Lines | ForEach-Object {
                $rects = @($_.Words | ForEach-Object { $_.BoundingRect })
                [pscustomobject]@{
                    text = $_.Text
                    y    = [int](($rects | Measure-Object -Property Y -Minimum).Minimum)
                    h    = [int](($rects | Measure-Object -Property Height -Maximum).Maximum)
                } })
        $frames.Add([pscustomobject]@{ frame = $_.Name; height = $bitmap.PixelHeight; lines = $lines })
    }
    finally { $stream.Dispose() }
}
$json = ConvertTo-Json -InputObject @($frames.ToArray()) -Depth 5 -Compress
[System.IO.File]::WriteAllText($Out, $json, (New-Object System.Text.UTF8Encoding($false)))
