# Deployment target table.
# No credentials, private keys, or auth material may be stored in this file.
# prod = production (dev.kleva.ru).  vm3 = local VMware test machine (NOT prod).
@{
    prod = @{
        # Production server: dev.kleva.ru
        # WARNING: this is real prod — destructive testing must NOT be done here.
        HostName    = 'dev.kleva.ru'
        Port        = 1452
        User        = 'root'
        # Default key resolved at runtime; override with -KeyPath if needed.
        KeyPath     = '$env:USERPROFILE\.ssh\id_ed25519_dev_kleva_codex'
        SshAlias    = 'dev-kleva-codex'
        RemoteDir   = '/root/multiserversubgen-live'
        HealthUrl   = 'http://127.0.0.1:666/health'
        UiUrlPath   = '/y4cooovh/'
        AppPort     = 666
        # Require clean main branch and passing CI checks before deploy.
        RequireMain = $true
        LocalTest   = $false
    }
    vm3  = @{
        # vm3.kleva.ru — local VMware machine for pre-prod testing.
        # NOT production.  Use for destructive / experimental deploys.
        HostName    = 'vm3.kleva.ru'
        Port        = 22
        User        = 'vm3'
        KeyPath     = ''
        SshAlias    = 'vm3'
        RemoteDir   = '/root/multiserversubgen-live'
        HealthUrl   = 'http://127.0.0.1:666/health'
        UiUrlPath   = '/y4cooovh/'
        AppPort     = 666
        RequireMain = $false
        LocalTest   = $true
    }
}
