# Deployment target table.
# No credentials, private keys, or auth material may be stored in this file.
# prod = production (example.invalid).  vm3 = local VMware test machine (NOT prod).
@{
    prod = @{
        # Production server: example.invalid
        # WARNING: this is real prod — destructive testing must NOT be done here.
        HostName    = 'example.invalid'
        Port        = 1452
        User        = 'root'
        # Default key resolved at runtime; override with -KeyPath if needed.
        KeyPath     = '<path-to-ssh-key>'
        SshAlias    = 'dev-kleva-codex'
        RemoteDir   = '<user-home>/multiserversubgen-live'
        HealthUrl   = 'http://127.0.0.1:666/health'
        UiUrlPath   = '/<panel-base-path>/'
        AppPort     = 666
        # Require clean main branch and passing CI checks before deploy.
        RequireMain = $true
        LocalTest   = $false
    }
    vm3  = @{
        # host-a.example.invalid — local VMware machine for pre-prod testing.
        # NOT production.  Use for destructive / experimental deploys.
        HostName    = 'host-a.example.invalid'
        Port        = 22
        User        = 'vm3'
        KeyPath     = ''
        SshAlias    = 'vm3'
        RemoteDir   = '<user-home>/multiserversubgen-live'
        HealthUrl   = 'http://127.0.0.1:666/health'
        UiUrlPath   = '/<panel-base-path>/'
        AppPort     = 666
        RequireMain = $false
        LocalTest   = $true
    }
}
