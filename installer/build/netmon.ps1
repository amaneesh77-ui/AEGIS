<#
Polls active TCP connections every 500ms and logs ONLY those whose owning
process executable lives under the AEGIS install directory (or is named
ollama/python and was launched from there). This machine has a lot of
unrelated background traffic (Teams/Outlook/OneDrive/IDE/etc.), so a global
"zero connections" check would be meaningless noise - what actually matters
for proving the offline install/launch is whether OUR installed processes
(the bundled Ollama, the bundled Python running uvicorn) ever try to reach
the network.
#>
param(
    [string]$LogPath = "C:\AEGIS\installer\build\netmon.log",
    [string]$WatchPathPrefix = "$env:LOCALAPPDATA\AEGIS"
)

"=== netmon started $(Get-Date -Format o), watching processes under $WatchPathPrefix ===" | Out-File -FilePath $LogPath -Append
$seen = @{}
while ($true) {
    try {
        $procs = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
            Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($WatchPathPrefix, [System.StringComparison]::OrdinalIgnoreCase) }
        foreach ($p in $procs) {
            $key = "proc:$($p.ProcessId)"
            if (-not $seen.ContainsKey($key)) {
                $seen[$key] = $true
                Add-Content -Path $LogPath -Value "$(Get-Date -Format o)  NEW AEGIS PROCESS: PID=$($p.ProcessId) $($p.ExecutablePath) args=$($p.CommandLine)"
            }
        }
        $watchedPids = $procs | Select-Object -ExpandProperty ProcessId
        if ($watchedPids) {
            $conns = Get-NetTCPConnection -ErrorAction SilentlyContinue | Where-Object { $watchedPids -contains $_.OwningProcess }
            foreach ($c in $conns) {
                $ckey = "conn:$($c.OwningProcess):$($c.LocalPort):$($c.RemoteAddress):$($c.RemotePort):$($c.State)"
                if (-not $seen.ContainsKey($ckey)) {
                    $seen[$ckey] = $true
                    Add-Content -Path $LogPath -Value "$(Get-Date -Format o)  CONN PID=$($c.OwningProcess)  $($c.LocalAddress):$($c.LocalPort) -> $($c.RemoteAddress):$($c.RemotePort)  State=$($c.State)"
                }
            }
        }
    } catch {}
    Start-Sleep -Milliseconds 500
}
