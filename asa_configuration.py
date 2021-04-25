from net_sec_lib.kasa.resource import Metadata, NamespaceKeys
from net_sec_lib.kasa.v1.asaconfiguration import ASAConfiguration, ASAConfigurationSpec
from net_sec_lib.kasa.resource_template import ResourceTemplate

# This file contains an example/template of ASAConfiguration that can be used in the tests

example_1_asa_configuration: ResourceTemplate[ASAConfiguration] = ResourceTemplate[ASAConfiguration](
    ASAConfiguration(
        metadata=Metadata(
            name='example-1-asa-configuration',
            namespace_key=NamespaceKeys.tenant1
        ),
        spec=ASAConfigurationSpec(
            description='This is an example/template ASAConfiguration that defines a network object',
            cli_lines='''\
object network example-asa-config-network-object-1
 host 1.1.1.1
'''
        )
    )
)

example_2_asa_configuration: ResourceTemplate[ASAConfiguration] = ResourceTemplate[ASAConfiguration](
    ASAConfiguration(
        metadata=Metadata(
            name='example-2-asa-configuration',
            namespace_key=NamespaceKeys.tenant1
        ),
        spec=ASAConfigurationSpec(
            description='This is another example/template ASAConfiguration that defines a network object',
            cli_lines='''\
object network example-asa-config-network-object-2
 host 1.1.1.2
'''
        )
    )
)
