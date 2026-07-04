# Regenerate the sample earnings-call audio used by the ingestion test.
#
# WHY PowerShell/System.Speech: it's an offline TTS built into Windows, so a
# fresh checkout can regenerate real *spoken* audio (not silence) for the ASR
# pipeline without any cloud dependency. data/ is gitignored, so this stands in
# for a manually-provided earnings-call recording.
#
# Usage (from repo root, in PowerShell):
#   ./apps/api/ingestion/generate_sample_audio.ps1

param(
    [string]$OutPath = "data/transcripts/sample_earnings_call.wav"
)

Add-Type -AssemblyName System.Speech
$full = [System.IO.Path]::GetFullPath($OutPath)
New-Item -ItemType Directory -Force -Path (Split-Path $full) | Out-Null

$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$s.SetOutputToWaveFile($full)
$text = @"
Good morning everyone, and welcome to the Acme Industries first quarter earnings call.
Revenue for the quarter grew fourteen percent year over year, driven by strong volumes in our industrial segment.
Operating margins expanded as input costs declined.
The board has recommended an interim dividend subject to shareholder approval.
We remain confident in our outlook for the full year.
Thank you, and we will now take your questions.
"@
$s.Speak($text)
$s.Dispose()

Write-Host "wrote $full ($((Get-Item $full).Length) bytes)"
