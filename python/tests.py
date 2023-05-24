import unittest
import socket
import requests
import json

from unittest.mock import MagicMock
from socketserver import TCPServer
from threading import Thread
from kubernetes import client, config
from kubernetes.client.models import VersionInfo

from app import app

class TestGetKubernetesVersion(unittest.TestCase):
    def test_good_version(self):
        api_client = client.ApiClient()

        version = VersionInfo(
            build_date="",
            compiler="",
            git_commit="",
            git_tree_state="fake",
            git_version="1.25.0-fake",
            go_version="",
            major="1",
            minor="25",
            platform=""
        )
        api_client.call_api = MagicMock(return_value=version)

        version = app.get_kubernetes_version(api_client)
        self.assertEqual(version, "1.25.0-fake")

    def test_exception(self):
        api_client = client.ApiClient()
        api_client.call_api = MagicMock(side_effect=ValueError("test"))

        with self.assertRaisesRegex(ValueError, "test"):
            app.get_kubernetes_version(api_client)


class TestAppHandler(unittest.TestCase):
    def setUp(self):
        super().setUp()

        port = self._get_free_port()
        self.mock_server = TCPServer(("localhost", port), app.AppHandler)

        # Run the mock TCP server with AppHandler on a separate thread to avoid blocking the tests.
        self.mock_server_thread = Thread(target=self.mock_server.serve_forever)
        self.mock_server_thread.daemon = True
        self.mock_server_thread.start()

    def _get_free_port(self):
        """Returns a free port number from OS"""
        s = socket.socket(socket.AF_INET, type=socket.SOCK_STREAM)
        s.bind(("localhost", 0))
        __, port = s.getsockname()
        s.close()

        return port

    def _get_url(self, target):
        """Returns a URL to pass into the requests so that they reach this suite's mock server"""
        host, port = self.mock_server.server_address
        return f"http://{host}:{port}/{target}"
    
    def test_healthz_ok(self):
        resp = requests.get(self._get_url("healthz"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(json.loads(resp.text), "ok")

    def test_create_network_policy(self):

        config.load_kube_config(config_file="~/.kube/config")
        data = {
                "policy": {
                    "name": "test-policy",
                    "workloads": [
                        {
                            "namespace": "default",
                            "labels": {
                                "app": "nginx"
                            }
                        },
                        {
                            "namespace": "second",
                            "labels": {
                                "app": "nginx2"
                            }
                        }
                    ]
                }
            }

        resp = requests.post(self._get_url("create/network-policy"), data=json.dumps(data))
        resp_body = resp.json()
        namespaces = [item["namespace"] for item in resp_body]
        messages = [item["message"] for item in resp_body]

        match resp.status_code:
            case 201:
                self.assertListEqual(namespaces, [data["policy"]["workloads"][0]["namespace"], data["policy"]["workloads"][1]["namespace"]])
                self.assertIn("network policy successfully created", messages)
            case 409:
                self.assertListEqual(namespaces, [data["policy"]["workloads"][0]["namespace"], data["policy"]["workloads"][1]["namespace"]])
                self.assertIn('networkpolicies.networking.k8s.io "test-policy" already exists', messages)
            case 500:
                self.assertEqual(resp.text, "Unknown error")

    def test_get_deployment_replicas(self):
        config.load_kube_config(config_file="~/.kube/config")
        resp = requests.get(self._get_url("deployments/all/replicas"))
        resp_body = resp.json()
        match resp.status_code:
            case 200:
                self.assertGreaterEqual(len(resp_body["Deployments"]), 1)
                for deployment in resp_body["Deployments"].values():
                    self.assertListEqual(list(deployment.keys()), ["Name", "Namespace", "Desired", "Available"])
            case 500:
                self.assertIn(resp_body.keys(), "error")

    def test_liveness_check(self):
        config.load_kube_config(config_file="~/.kube/config")
        resp = requests.get(self._get_url("cluster/health"))
        resp_body = resp.json()
        match resp.status_code:
            case 200:
                self.assertDictEqual(resp_body, {"clusterStatus": "live"})
            case _:
                self.assertIn("clusterStatus", list(resp_body.keys()))
if __name__ == '__main__':
    unittest.main()
