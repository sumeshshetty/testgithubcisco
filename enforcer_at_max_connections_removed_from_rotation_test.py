"""
Name: scale_up_enfor_limit_session_test.py
Purpose: [UPDATE ME]
Author: sumeshet
"""
import a_test_2
import logging
from typing import Tuple
import time
from pyats import aetest
from pyats.aetest.steps import Steps
from assertpy import assert_that
import re
from net_sec_lib.k8s.k8s import Kubernetes
from net_sec_lib.kasa.client import KasaConfigClient
from net_sec_lib.kasa.resource import KASA_ENFORCER_NAME
from net_sec_lib.kasa.k8s_kasa import KubernetesKASA
from net_sec_lib.kasa.v1.asaconfiguration import ASAConfiguration
from net_sec_lib.kasa.testbed import KASATestbed
from net_sec_lib.kasa.resource import NamespaceKeys
from testscripts.serviceability.resources.serviceability import ENFORCER_LABEL
from testscripts.vpn.resources.common.constants import TEST_NAMESPACE_KEY
from testscripts.autoscaling.resources.manual_autoscaling.config import simple_config_template
from testscripts.common_utils import reduce_autoscaler_downscale_time
from testscripts.global_common_classes import CommonSetup, CommonCleanup, Testcase
from testscripts.vpn.resources.common.asaconfiguration_crd import asacommand_show_vpn_sessiondb, \
    asaconfiguration_interfaces, asaconfiguration
from testscripts.vpn.resources.common.asaconfig_certificate import SECRET_NAME_VPN_CERT
from testscripts.common_resources.asacommand_show_network_config import asacommand_show_network_objects
from testscripts.vpn.resources.common.constants import SECRET_NAME, CLIENT_HOST, VPN_HOST_NAME, NO_SUDO_STATE_CMD
from testscripts.vpn.resources.enforcer_at_max_connections_removed_from_rotation_test.redis_certificate \
    import SECRET_NAME_REDIS_CERT
from testscripts.vpn.resources.common.vpn_test_common import setup_vpn_server_with_session_reconnect, delete_secrets
from testscripts.vpn_clients_controller import VpnClientController
from testscripts.vpn.resources.enforcer_at_max_connections_removed_from_rotation_test.max_vpn_config \
    import max_vpn_config_object,MAX_VPN_CONNECTIONS
from testscripts.vpn.resources.common.vpn_test_common import get_enforcer_name_to_which_client_connected

log = logging.getLogger(__name__)

SCRIPT_SUPPORTED_PLATFORMS = ("openstack", "aws")

parameters = {'tenant': ''}
# pyats has this as the same object as the one referenced by self.parent.parameters in test
ep_deployment_name = "kasa-enforcer"
cluster_autoscaler_deployment_name = "autoscaler-aws-cluster-autoscaler"

TENANT_NAMESPACE = NamespaceKeys.tenant1

class Setup(CommonSetup):
    script_supported_platforms: Tuple[str] = SCRIPT_SUPPORTED_PLATFORMS

    @aetest.subsection
    def _custom_setup(self, steps: Steps, testbed: KASATestbed):
        log.info("Common setup is executed")
        kasa_client: KasaConfigClient = self.parent.parameters.get('kasa_client')
        namespace = testbed.get_tenant_namespace(TEST_NAMESPACE_KEY)
        self.parent.parameters.update(namespace=namespace)
        with steps.start("Get initial number of replicas"):
            ep_deployment = kasa_client.get_ep_deployment(KASA_ENFORCER_NAME, namespace)
            log.info(f'Started with {ep_deployment.spec.replicas} replica(s)')
            self.parent.parameters.update(initial_ep_replicas=ep_deployment.spec.replicas)

        with steps.start(f"Make sure we have at least 2 enforcers"):
            ep_deployment = kasa_client.get_ep_deployment(KASA_ENFORCER_NAME, namespace)
            if ep_deployment.spec.replicas < 2:
                try:
                    ep_deployment=kasa_client.update_ep_deployment_replicas(ep_deployment,
                                                                            namespace, KASA_ENFORCER_NAME,
                                                              ep_deployment.spec.replicas + 1)
                    if ep_deployment.spec.replicas==2:

                        log.info(f"Sucessfully scaled up to {ep_deployment.spec.replicas}")
                except Exception:
                    log.error(f'Failure in scalling replicas')



    @aetest.subsection
    def create_necessary_crds_for_ravpn_config(self, steps: Steps):
        with steps.start(f"configure RAVPN"):
            setup_vpn_server_with_session_reconnect(self, steps)
            host = VpnClientController(CLIENT_HOST)
            self.parent.parameters.update(host=host)


class enforcer_at_max_connections_removed_from_rotation_job(Testcase):
    """
    Author:
       sumeshet

    Description:
        Verify a redirector stops distributing sessions to an enforcer that reaches max connections (250)

    Test Steps:
        1. Create CRD which will limit to 5 the maximum clients which can connect to an enforcer
        2. Connect clients to VPN until the first enforcer gets maxed out

        3.pass the rejected connection to redirector

    Pass/Fail Criteria:
        Test passes if these checks pass:
        1. Clients/Sesssion are rejected by 1st enforcer after getting maxed out
        2.Redirecotr send the conections to 2nd enforcer
        Test fails due to these scenarios:
        1.Sessions are accepted by enforcer after maxing out
        2.Redirector sends the connection to maxed out enforcer
    """



    @aetest.setup
    def apply_max_session_config_create_clients(self,steps: Steps, kasa_client: KasaConfigClient, tenant: str,
                 testbed: KASATestbed,host,k8s: Kubernetes,namespace):
        with steps.start(f"Setup max limit of VPN connections :{MAX_VPN_CONNECTIONS}"):
            kasa_client.create_resource(max_vpn_config_object.resolve(testbed))
            time.sleep(15)
            log.info(f' Max VPN connection  is: {MAX_VPN_CONNECTIONS}')


        with steps.start(f"Get Route53 Enforcer address"):

            actual_enforcers: list = \
                k8s.list_pods(namespace=namespace, label_selector=ENFORCER_LABEL)


            enf_ips_names = [
                (item.metadata.labels['kasa.cisco.com.interface.2/public-ip'].replace('.', '-'),
                 item.metadata.name) for
                item in actual_enforcers.items]

            enforcer_name=enf_ips_names[0][0] + '.' + VPN_HOST_NAME
            self.parent.parameters.update(enforcer_name=enforcer_name)


        with steps.start(f"Creating {MAX_VPN_CONNECTIONS+1} client containers"):
            host_ids = host.create_vpn_clients(MAX_VPN_CONNECTIONS+1)
            self.parent.parameters.update(host_ids=host_ids)

        with steps.start('Waiting for DNS record propagation'):
            host.wait_for_dns_record_propagation(enforcer_name)



    @aetest.test
    def test_ravpn_connection_on_first_enforcer(self, steps: Steps,testbed: KASATestbed,kasa_client: KasaConfigClient,
                                                enforcer_name,host,host_ids):
        with steps.start('Connecting clients to first enforcer'):
            host_ids_rejected=[]
            responses = host.connect_clients_to_vpn_server(host_ids,enforcer_name)

            for response in responses:

                try:

                    assert_that(response[1],
                                f"Connection response from client {response[0]}  contains "
                                f"expected string").contains("state: Connected")
                    log.info(f"client: {response[0]} connected to {enforcer_name}")

                except Exception as e:

                    log.info(f"client: {response[0]} rejected by  {enforcer_name}")
                    log.info(f"enforcer  {enforcer_name} maxed out {MAX_VPN_CONNECTIONS}")
                    host_ids_rejected.append(response[0])
                    self.parent.parameters.update(host_ids_rejected=host_ids_rejected)


        with steps.start('getting enforcer name of maxed out session'):
            responses = kasa_client.execute_asa_command(asacommand_show_vpn_sessiondb.resolve(testbed))

            for out in responses['items']:
                if not "No sessions to display" in out['spec']['response'] \
                        and  re.search(f"AnyConnect Client *: *{MAX_VPN_CONNECTIONS}",out['spec']['response']):
                    first_enforcer_pod_name = out['spec']['podName']
            log.info(f"First enforcer pod name {first_enforcer_pod_name}")
            self.parent.parameters.update(first_enforcer_pod_name=first_enforcer_pod_name)

    @aetest.test
    def checking_second_enforcer_has_no_sessions(self, host, first_enforcer_pod_name,steps: Steps,
                                      testbed: KASATestbed,
                                      kasa_client: KasaConfigClient):
        with steps.start('getting sessions on second enforcer'):
            responses = kasa_client.execute_asa_command(asacommand_show_vpn_sessiondb.resolve(testbed))

            for out in responses['items']:


                if  out['spec']['podName']!=first_enforcer_pod_name and \
                         "vpnredirector" not in out['spec']['podName']  and\
                        ( re.search("AnyConnect Client *: *0", out['spec']['response']) or \
                        "No sessions to display" in out['spec']['response']) :

                    log.info(f"enforcer {out['spec']['podName']} contains 0 sessions")
                    second_enforcer_pod_name = out['spec']['podName']

            log.info(f"No session in {second_enforcer_pod_name}")
            self.parent.parameters.update(second_enforcer_pod_name=second_enforcer_pod_name)


    @aetest.test
    def pass_connection_to_redirector(self,host,host_ids_rejected,second_enforcer_pod_name, steps: Steps,
                                      testbed: KASATestbed,kasa_client: KasaConfigClient):
        with steps.start('Trying to connect rejected clients to 2nd enforcer via redirector '):
            red_responses = host.connect_clients_to_vpn_server(host_ids_rejected, VPN_HOST_NAME)

            responses = kasa_client.execute_asa_command(asacommand_show_vpn_sessiondb.resolve(testbed))
            for out in responses['items']:
                if out['spec']['podName']==second_enforcer_pod_name and \
                        re.search("AnyConnect Client *: *1", out['spec']['response']):

                    log.info(f"Sucessfully connected to {second_enforcer_pod_name}")




    @aetest.cleanup
    def cleanup_clients(self, host,host_ids,steps: Steps):
        with steps.start('Disconnecting clients from VPN server'):
            host.disconnect_clients_from_vpn_server(host_ids)
        with steps.start('Deleting client containers'):
            host.remove_vpn_clients(host_ids)
        with steps.start("deleteing secrets ,certificates and resources !!"):
            log.info("Common cleanup is executed")
            self.delete_all_active_kasa_resources(steps)
            k8s = self.parent.parameters.get('k8s')
            testbed = self.parent.parameters.get('testbed')
            delete_secrets([SECRET_NAME, SECRET_NAME_VPN_CERT, SECRET_NAME_REDIS_CERT], testbed, k8s)





class Cleanup(CommonCleanup):
    def _custom_cleanup(self,namespace,initial_ep_replicas,kasa_client: KasaConfigClient,steps: Steps, **kwargs):
        with steps.start("Delete created ASAConfiguration"):
            self.delete_all_active_kasa_resources(steps)

        with steps.start(f"Scaling down the cluster to {initial_ep_replicas} replicas"):
            ep_deployment = kasa_client.get_ep_deployment(KASA_ENFORCER_NAME, namespace)
            kasa_client.update_ep_deployment_replicas(ep_deployment, namespace, KASA_ENFORCER_NAME,
                                                      initial_ep_replicas)
