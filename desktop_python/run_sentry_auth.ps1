if (-not $env:SENTRY_SETUP_CODE) {
    $env:SENTRY_SETUP_CODE = Read-Host "Enter SENTRY_SETUP_CODE (never commit this token to git)"
}
if (-not $env:SENTRY_SETUP_CODE) {
    Write-Error "SENTRY_SETUP_CODE is required."
    exit 1
}
& "$env:USERPROFILE\.local\bin\sentry.exe" auth bootstrap

