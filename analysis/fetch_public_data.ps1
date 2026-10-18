param(
    [string]$OutputDirectory = 'data/raw/juliete',
    [int]$MaxSubjects = 0,
    [switch]$InventoryOnly
)
$ErrorActionPreference = 'Stop'
$releaseUrl = 'https://drive.google.com/drive/folders/1ijWfyNYktqKV0ACpgCNOLuhJf8YsWYfB'
$destination = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot $OutputDirectory))
$workspace = [IO.Path]::GetFullPath($PSScriptRoot) + [IO.Path]::DirectorySeparatorChar
if (-not $destination.StartsWith($workspace, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'OutputDirectory must be inside the analysis workspace.'
}
New-Item -ItemType Directory -Force -Path $destination | Out-Null
function Get-PublicEntries([string]$Url) {
    $content = (Invoke-WebRequest -Uri $Url -TimeoutSec 45).Content
    $entries = @{}
    foreach ($tag in [regex]::Matches($content, '<[^>]+data-tooltip="[^"]+"[^>]*>')) {
        $id = [regex]::Match($tag.Value, 'data-id="([^"]+)"').Groups[1].Value
        $label = [Net.WebUtility]::HtmlDecode([regex]::Match($tag.Value, 'data-tooltip="([^"]+)"').Groups[1].Value)
        if ($id) { $entries[$id] = [pscustomobject]@{ id=$id; label=$label } }
    }
    return $entries.Values
}
$subjects = @(Get-PublicEntries $releaseUrl | Where-Object label -Match '^\d{4} Shared folder$' | Sort-Object label)
if ($MaxSubjects -gt 0) { $subjects = @($subjects | Select-Object -First $MaxSubjects) }
$records = @()
foreach ($subject in $subjects) {
    Write-Host ('Listing ' + $subject.label)
    $entries = Get-PublicEntries ('https://drive.google.com/drive/folders/' + $subject.id)
    foreach ($entry in $entries | Sort-Object label) {
        if ($entry.label -notmatch '^(\d{4}_[^ ]+_(EEG|Transforms|SubjectiveCs)) Google Sheets$') { continue }
        $name = $Matches[1]
        $path = Join-Path $destination ($name + '.csv')
        $url = 'https://docs.google.com/spreadsheets/d/' + $entry.id + '/export?format=csv'
        $status = 'listed'
        $failure = ''
        if (-not $InventoryOnly) {
            try {
                if (-not (Test-Path -LiteralPath $path)) {
                    Invoke-WebRequest -Uri $url -OutFile ($path + '.part') -TimeoutSec 60
                    Move-Item -LiteralPath ($path + '.part') -Destination $path
                }
                $status = 'downloaded'
            } catch { $status = 'failed'; $failure = $_.Exception.Message }
        }
        $hash = if (Test-Path -LiteralPath $path) { (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash } else { '' }
        $records += [pscustomobject]@{ name=$name; id=$entry.id; url=$url; file=($name+'.csv'); status=$status; sha256=$hash; error=$failure }
        Write-Host ($name + ': ' + $status)
        $records | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $destination 'acquisition.json') -Encoding utf8
    }
}
Write-Host ('Completed directory pass: ' + $records.Count + ' streams. Download errors remain recorded in acquisition.json.')
if (@($records | Where-Object status -EQ 'failed').Count -gt 0) { exit 1 }
