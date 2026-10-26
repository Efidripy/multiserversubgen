# Deployment target template. Copy this file to targets.local.psd1 and fill it locally.
# Local configuration is ignored by Git and is required by deploy.ps1.
@{
    prod = @{
        HostName    = 'example.invalid'
        Port        = '<ssh-port>'
        User        = '<ssh-user>'
        KeyPath     = '<path-to-ssh-key>'
        SshAlias    = '<ssh-user>@example.invalid'
        RemoteDir   = '<user-home>/multiserversubgen-live'
        HealthUrl   = 'http://127.0.0.1:666/health'
        UiUrlPath   = '/<panel-base-path>/'
        AppPort     = 666
        RequireMain = $true
        LocalTest   = $false
    }
    vm3  = @{
        HostName    = 'host-a.example.invalid'
        Port        = '<ssh-port>'
        User        = '<ssh-user>'
        KeyPath     = '<path-to-ssh-key>'
        SshAlias    = '<ssh-user>@host-a.example.invalid'
        RemoteDir   = '<user-home>/multiserversubgen-live'
        HealthUrl   = 'http://127.0.0.1:666/health'
        UiUrlPath   = '/<panel-base-path>/'
        AppPort     = 666
        RequireMain = $false
        LocalTest   = $true
    }
}
