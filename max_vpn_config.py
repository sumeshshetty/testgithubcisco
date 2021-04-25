from net_sec_lib.kasa.resource import Metadata, NamespaceKeys
from net_sec_lib.kasa.v1.asaconfiguration import ASAConfiguration, ASAConfigurationSpec
from net_sec_lib.kasa.resource_template import ResourceTemplate
MAX_VPN_CONNECTIONS = 5

max_vpn_config_object: ResourceTemplate[ASAConfiguration] = ResourceTemplate[ASAConfiguration](
    ASAConfiguration(
        metadata=Metadata(
            name='max-vpn-config',
            namespace_key=NamespaceKeys.tenant1
        ),
        spec=ASAConfigurationSpec(
            order=4,
            description=f'Limit to {MAX_VPN_CONNECTIONS} the number of VPN connections to an enforcer.',
            cli_lines=f'''\
vpn-sessiondb max-anyconnect-premium-or-essentials-limit {MAX_VPN_CONNECTIONS}
vpn-sessiondb max-session-limit {MAX_VPN_CONNECTIONS}
username vpnuser attributes
vpn-simultaneous-logins 250
'''
        )
    )
)