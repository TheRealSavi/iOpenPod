#Requires -RunAsAdministrator
#Requires -Version 5.1
<#
Validate a hash-pinned, locally signed candidate, then remove its installation
and any certificate trust added by this run. Never use on an existing install.
The JSON plan is generated beside the local candidate, not shipped to customers.
The same-payload baseline tests package upgrade, not legacy user-data migration.
#>
param([Parameter(Mandatory = $true)][string]$Plan)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$configuration = Get-Content -LiteralPath $Plan -Raw | ConvertFrom-Json
$appName = 'TheRealSavi.iOpenPod'
$publisher = 'CN=FB5CD908-9397-4B6A-B014-49E83AB6CE1A'
$familyName = 'TheRealSavi.iOpenPod_gncxjke9mmtsj'
$certificatePath = [string]$configuration.certificate
$thumbprint = [string]$configuration.certificateThumbprint
$reportDirectory = [string]$configuration.reportDirectory
$appCert = [string]$configuration.appCert
$signTool = [string]$configuration.signTool
if (Get-AppxPackage -AllUsers -Name $appName) {
    throw 'An existing iOpenPod installation must be preserved. Use a separate test machine.'
}
if (Get-Process appcert,appcertui -ErrorAction SilentlyContinue) {
    throw 'Another Certification Kit session is active.'
}
if (Test-Path -LiteralPath $reportDirectory) {
    throw 'The report directory must be new to preserve earlier validation evidence.'
}
foreach ($toolPath in @($appCert, $signTool)) {
    if (-not (Test-Path -LiteralPath $toolPath -PathType Leaf)) {
        throw ('Missing Windows SDK tool: ' + $toolPath)
    }
}
Add-Type -AssemblyName System.IO.Compression.FileSystem
$packageVersions = @()
foreach ($item in @($configuration.baseline, $configuration.candidate)) {
    if ((Get-FileHash -LiteralPath $item.path -Algorithm SHA256).Hash -ne $item.sha256) {
        throw ('Unexpected package hash: ' + $item.path)
    }
    $signature = Get-AuthenticodeSignature -LiteralPath $item.path
    if ($null -eq $signature.SignerCertificate -or $signature.SignerCertificate.Thumbprint -ne $thumbprint) {
        throw ('Unexpected package signer: ' + $item.path)
    }
    $archive = [IO.Compression.ZipFile]::OpenRead([string]$item.path)
    try {
        $entry = $archive.GetEntry('AppxManifest.xml')
        if ($null -eq $entry) { throw 'The package manifest is missing.' }
        $reader = [IO.StreamReader]::new($entry.Open())
        try { [xml]$manifest = $reader.ReadToEnd() }
        finally { $reader.Dispose() }
        $identity = $manifest.Package.Identity
        if ($identity.Name -ne $appName -or $identity.Publisher -ne $publisher -or $identity.ProcessorArchitecture -ne 'x64') {
            throw 'The package identity is not the expected Windows x64 test application.'
        }
        $application = @($manifest.Package.Applications.Application)
        if ($application.Count -ne 1 -or $application[0].Id -ne 'iOpenPod' -or $application[0].Executable -ne 'app\iOpenPod.exe') {
            throw 'The package does not contain the expected application entry point.'
        }
        $packageVersions += [version]$identity.Version
    }
    finally { $archive.Dispose() }
}
if ($packageVersions[0] -ge $packageVersions[1] -or $packageVersions[1] -ne [version]$configuration.version) {
    throw 'The baseline must precede the candidate, whose version must match the plan.'
}
$certificate = [Security.Cryptography.X509Certificates.X509Certificate2]::new($certificatePath)
if ($certificate.Thumbprint -ne $thumbprint -or $certificate.NotAfter -lt (Get-Date) -or $certificate.NotBefore -gt (Get-Date)) {
    $certificate.Dispose()
    throw 'The temporary signing certificate does not match or is outside its validity period.'
}
if ($certificate.Subject -ne $publisher) {
    $certificate.Dispose()
    throw 'The test certificate does not match the reserved Store publisher.'
}
New-Item -ItemType Directory -Path $reportDirectory -ErrorAction Stop | Out-Null
$trustedPath = 'Cert:\LocalMachine\TrustedPeople\' + $thumbprint
$addedTrust = $false
$installedByThisRun = $false
$transcriptStarted = $false
$failure = $null
$cleanupErrors = @()
$results = [ordered]@{
    candidateSha256 = $configuration.candidate.sha256
    baselineSha256 = $configuration.baseline.sha256
    baselineVersion = $packageVersions[0].ToString()
    candidateVersion = $packageVersions[1].ToString()
    upgradeScope = 'Same payload with lower package version; no legacy-data migration is claimed.'
    install = 'PENDING'; launch = 'PENDING'; upgrade = 'PENDING'
    upgradedLaunch = 'PENDING'; uninstall = 'PENDING'; wack = 'PENDING'
    cleanup = 'PENDING'
    launchDiagnostics = @()
}

function Get-TestInstallation {
    $packages = @(Get-AppxPackage -Name $appName)
    foreach ($package in $packages) {
        if ($package.PackageFamilyName -ne $familyName -or $package.Publisher -ne $publisher -or
            $packageVersions -notcontains [version]$package.Version) {
            throw 'An unexpected installation appeared; it will not be removed by this run.'
        }
    }
    return $packages
}

function Test-PackageLaunch([string]$ReportName) {
    $smokeReport = Join-Path $reportDirectory $ReportName
    if (Test-Path -LiteralPath $smokeReport) { throw 'A runtime report already exists.' }
    $arguments = '--smoke-test --smoke-test-report "' + $smokeReport + '"'
    $appProcessId = [iOpenPodValidation.Launcher]::Launch(($familyName + '!iOpenPod'), $arguments)
    $diagnostic = [ordered]@{
        report = $ReportName; processId = $appProcessId
        exitCode = $null; exitObservation = 'pending'
    }
    $results.launchDiagnostics += $diagnostic
    try {
        $exitCode = [iOpenPodValidation.Launcher]::WaitForExit($appProcessId, 180000)
    }
    catch {
        $diagnostic.exitObservation = 'observation-failed'
        throw
    }
    $diagnostic.exitCode = $exitCode
    if ($null -eq $exitCode) {
        $diagnostic.exitObservation = 'process-ended-before-handle-open; fresh-report-required'
    }
    else {
        $diagnostic.exitObservation = 'observed'
        if ($exitCode -ne 0) {
            throw ('Installed runtime validation returned failure exit code: ' + $exitCode)
        }
    }
    if (-not (Test-Path -LiteralPath $smokeReport)) {
        throw 'Installed application did not produce a runtime report.'
    }
    if ((Get-Content -LiteralPath $smokeReport -Raw).Trim() -ne 'iOpenPod packaged runtime check passed.') {
        throw ('Installed runtime check failed: ' + $smokeReport)
    }
}

try {
    Start-Transcript -LiteralPath (Join-Path $reportDirectory 'validation.log') | Out-Null
    $transcriptStarted = $true
    Add-Type -Path (Join-Path $PSScriptRoot 'ActivatePackage.cs')
    if (-not (Test-Path -LiteralPath $trustedPath)) {
        Import-Certificate -FilePath $certificatePath -CertStoreLocation 'Cert:\LocalMachine\TrustedPeople' | Out-Null
        $addedTrust = $true
    }
    foreach ($item in @($configuration.baseline, $configuration.candidate)) {
        & $signTool verify /pa $item.path | Out-Host
        if ($LASTEXITCODE -ne 0) { throw 'Signature validation failed.' }
    }
    # Clear WACK state before creating our test installation. Installed runtime
    # validation and WACK's package-path workflow are recorded separately below.
    & $appCert reset | Out-Host
    if ($LASTEXITCODE -ne 0) { throw 'Certification Kit reset failed.' }
    # Baseline uses the same payload with a lower test-only package version.
    if (Get-AppxPackage -AllUsers -Name $appName) {
        throw 'An iOpenPod installation appeared after preflight; it must be preserved.'
    }
    # Set before deployment so a partial-success error is also cleaned up.
    $installedByThisRun = $true
    Add-AppxPackage -Path $configuration.baseline.path
    $installed = @(Get-TestInstallation)
    if ($installed.Count -ne 1 -or [version]$installed[0].Version -ne $packageVersions[0]) {
        throw 'The baseline was not installed with the expected identity and version.'
    }
    $results.install = 'PASS'
    Test-PackageLaunch 'baseline-smoke.txt'
    $results.launch = 'PASS'
    Add-AppxPackage -Path $configuration.candidate.path
    $installed = @(Get-TestInstallation)
    if ($installed.Count -ne 1 -or [version]$installed[0].Version -ne [version]$configuration.version) {
        throw 'Upgrade did not install the expected candidate version.'
    }
    $results.upgrade = 'PASS'
    Test-PackageLaunch 'candidate-smoke.txt'
    $results.upgradedLaunch = 'PASS'
    $installed = @(Get-TestInstallation)
    if ($installed.Count -ne 1 -or [version]$installed[0].Version -ne $packageVersions[1]) {
        throw 'The upgraded installation changed before the uninstall test.'
    }
    foreach ($package in $installed) {
        Remove-AppxPackage -Package $package.PackageFullName
    }
    if (Get-AppxPackage -Name $appName) { throw 'The temporary app did not uninstall.' }
    $installedByThisRun = $false
    $results.uninstall = 'PASS'
    # WACK's installed-package workflow lost the Centennial manifest path in the
    # recorded SDK run. Use its documented undeployed-package workflow while
    # retaining the independent, successful install/launch/upgrade evidence.
    if (@(Get-TestInstallation).Count -ne 0) {
        throw 'An installation appeared before package-path certification.'
    }
    $candidateHash = (Get-FileHash -LiteralPath $configuration.candidate.path -Algorithm SHA256).Hash
    if ($candidateHash -ne $configuration.candidate.sha256) {
        throw 'The candidate changed before package-path certification.'
    }
    $wackReport = Join-Path $reportDirectory 'wack.xml'
    $results.wackMode = 'package-path'
    $results.wackPackageSha256 = $candidateHash.ToLowerInvariant()
    $results.wackScope = 'Package-path workflow; installed launch, upgrade, and uninstall verified separately.'
    # WACK may deploy the supplied package; clean up only our verified identity.
    $installedByThisRun = $true
    & $appCert test -appxpackagepath $configuration.candidate.path -reportoutputpath $wackReport | Out-Host
    $results.wackExitCode = $LASTEXITCODE
    if ($LASTEXITCODE -ne 0) { throw 'Certification Kit returned a failure.' }
    [xml]$report = Get-Content -LiteralPath $wackReport -Raw
    $results.wackReportedResult = [string]$report.REPORT.OVERALL_RESULT
    $results.wackAppType = [string]$report.REPORT.APP_TYPE
    $results.wackPartialRun = [string]$report.REPORT.PARTIAL_RUN
    if ($report.REPORT.APP_NAME -ne $appName -or $report.REPORT.APP_VERSION -ne [string]$configuration.version) {
        throw 'Certification Kit report does not identify the expected candidate.'
    }
    if ($results.wackAppType -ne 'Centennial' -or $results.wackPartialRun -ne 'FALSE') {
        throw 'Certification Kit did not complete the expected desktop-package workflow.'
    }
    $results.wack = $results.wackReportedResult
    if ($results.wack -ne 'PASS') { throw 'Review Certification Kit findings.' }
}
catch {
    $failure = $_
    $results.error = $_.Exception.Message
}
finally {
    try {
        if ($installedByThisRun) {
            foreach ($package in @(Get-TestInstallation)) {
                Remove-AppxPackage -Package $package.PackageFullName
            }
            if (Get-AppxPackage -Name $appName) { throw 'The temporary app remains installed.' }
        }
    }
    catch { $cleanupErrors += ('Package cleanup: ' + $_.Exception.Message) }
    try {
        if ($addedTrust) { Remove-Item -LiteralPath $trustedPath }
    }
    catch { $cleanupErrors += ('Certificate cleanup: ' + $_.Exception.Message) }
    $certificate.Dispose()
    $results.cleanup = if ($cleanupErrors.Count -eq 0) { 'PASS' } else { 'FAIL' }
    if ($cleanupErrors.Count -gt 0) { $results.cleanupErrors = $cleanupErrors }
    try {
        $results | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $reportDirectory 'results.json') -Encoding UTF8
    }
    finally {
        if ($transcriptStarted) { Stop-Transcript | Out-Null }
    }
}
if ($null -ne $failure) { throw $failure }
if ($cleanupErrors.Count -gt 0) { throw ($cleanupErrors -join '; ') }
Write-Host ('Validation passed. Evidence: ' + $reportDirectory)
